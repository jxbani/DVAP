"""SafeEnvelope: a deterministic policy guard between the MCP tool handlers and the PLC.

No LLM is in the enforcement path; every decision follows from the policy, the live PLC
readings and a pure physics forecast. Each decision is published to the `guard.events` bus with
a plain-English reason. Off by default; a challenge turns it on in its "defended" mode.

Layers (see docs/SAFEENVELOPE.md):
 1. physical invariants  - absolute setpoint ranges, rate-of-change limits, forbidden combos
 2. predictive check     - forecast() 120 s ahead; deny if an incident/warning is predicted
 3. provenance / taint   - a manual override driven by untrusted content needs human approval
 4. privilege separation - engineering tools are refused for the operator identity
 5. honest decisions      - the record carries the raw call, forecast and provenance, not a summary
 6. kill switch / anomaly - repeated denied actions and tasks scheduled from untrusted context
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from dvap_common.plant_model import PlantState, forecast

# Context-id prefixes whose content is attacker-controllable (tickets, bus orders, vendor MCP
# output, memory written from an untrusted source). pv/alarms/device_strings/approval are not here.
UNTRUSTED_PREFIXES = ("ticket:", "workorder:", "bus:", "vendor:", "memory:untrusted")
SHELL_METACHARS = set(";&|`$\n><")
# Friendly setpoint tag -> PLC holding tag, for the current value a rate limit compares against.
SETPOINT_PLC = {"level_sp": "level_setpoint", "chlorine_sp": "chlorine_setpoint", "valve_pct": "valve_pct"}


@dataclass
class Decision:
    action: str  # "allow" | "deny" | "review" (review = needs human approval, not applied)
    tool: str
    args: dict
    reason: str = ""
    forecast: str = ""
    provenance: list[str] = field(default_factory=list)
    anomaly: bool = False

    @property
    def allowed(self) -> bool:
        return self.action == "allow"

    def public(self) -> dict:
        return {
            "action": self.action,
            "tool": self.tool,
            "args": self.args,
            "reason": self.reason,
            "forecast": self.forecast,
            "provenance": self.provenance,
            "anomaly": self.anomaly,
        }


def load_policy(path: str | Path | None = None) -> dict:
    path = path or Path(__file__).parent / "policies" / "plant.yaml"
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


class SafeEnvelope:
    def __init__(self, policy: dict, read_state, publish=None, identity: str = "operator"):
        self.p = policy
        self.read_state = read_state  # async () -> read_all(modbus) dict
        self.publish = publish  # async (event: dict) -> None, or None to not publish
        self.identity = identity
        self._denied: dict[str, int] = {}  # denied-action signature -> count (anomaly detection)

    async def decide(self, tool: str, args: dict, context_ids=()) -> Decision:
        plc = await self.read_state()
        prov = [c for c in (context_ids or []) if str(c).startswith(UNTRUSTED_PREFIXES)]
        d = self._decide(tool, args or {}, plc, prov)
        if d.action == "deny":
            key = json.dumps([tool, args], sort_keys=True, default=str)
            self._denied[key] = self._denied.get(key, 0) + 1
            if self._denied[key] >= self.p["anomaly_repeat_threshold"]:
                d.anomaly = True  # a denied action retried this often is a rogue agent, not a mistake
        return d

    async def record(self, d: Decision) -> None:
        if self.publish is not None:
            await self.publish({"type": "guard", **d.public()})

    # --- the policy (pure; `plc` is one read_all snapshot) ----------------

    def _decide(self, tool: str, args: dict, plc: dict, prov: list[str]) -> Decision:
        if tool in self.p["engineering_tools"]:  # layer 4
            return self._mk("deny", tool, args, prov,
                            "privilege separation: an engineering tool is not permitted for the operator identity")

        if tool == "set_setpoint":  # layer 1
            tag = str(args.get("tag"))
            try:
                value = float(str(args.get("value")))  # str() first: a missing value or a bool is refused
            except ValueError:
                return self._mk("deny", tool, args, prov, "non-numeric setpoint value")
            lim = self.p["setpoints"].get(tag)
            if lim and not (lim["min"] <= value <= lim["max"]):
                return self._mk("deny", tool, args, prov,
                                f"{tag}={value:g} is outside the safe range [{lim['min']:g}, {lim['max']:g}]")
            rate = self.p["rate_limits"].get(tag)
            cur = plc.get(SETPOINT_PLC.get(tag, ""))
            if rate is not None and cur is not None and abs(value - cur) > rate:
                return self._mk("deny", tool, args, prov,
                                f"{tag} step of {abs(value - cur):g} exceeds the max {rate:g} per change")
            return self._mk("allow", tool, args, prov, "within the safe operating range")

        if tool == "run_diagnostic":
            if SHELL_METACHARS & set(str(args.get("args", ""))):
                return self._mk("deny", tool, args, prov,
                                "diagnostic arguments contain shell metacharacters (command injection)")
            return self._mk("allow", tool, args, prov, "no shell metacharacters in the arguments")

        if tool == "schedule_task":  # layer 6: a scheduled task may only do what is allowed now
            inner = self._decide(str(args.get("tool")), args.get("args") or {}, plc, prov)
            if not inner.allowed:
                return self._mk("deny", tool, args, prov,
                                f"refuses to schedule a would-be-{inner.action} action ({inner.tool}): {inner.reason}",
                                anomaly=True)
            if prov:
                return self._mk("review", tool, args, prov, "scheduled task created from untrusted context")
            return self._mk("allow", tool, args, prov, f"the scheduled action {inner.tool} is permitted")

        if tool in ("set_actuator", "set_mode"):
            name = args.get("name")
            if tool == "set_actuator" and name in self.p["protected_off"] and not bool(args.get("state")):
                return self._mk("review", tool, args, prov,
                                f"stopping {name} removes disinfection and risks a slow underdose; needs human approval")
            change, pump, drain = self._actuator_change(tool, args, plc)
            if pump and drain <= 0.0 and float(plc["tank_level_pct"]) > self.p["forbidden"]["fill_level_above"]:  # layer 1
                return self._mk("deny", tool, args, prov,
                                f"forbidden combination: inflow pump on with the drain shut at {plc['tank_level_pct']:g}% level")
            if change is not None:  # layer 2
                when, inc = self._forecast(self._state(plc), change)
                if inc:
                    d = self._mk("deny", tool, args, prov, f"predicted {inc}")
                    d.forecast = f"forecast {inc} within {when}s"
                    return d
            if prov:  # layer 3
                return self._mk("review", tool, args, prov, "manual override driven by untrusted content; needs human approval")
            return self._mk("allow", tool, args, prov, "forecast clear over the horizon")

        return self._mk("allow", tool, args, prov, "no policy applies")

    # --- helpers ----------------------------------------------------------

    def _mk(self, action, tool, args, prov, reason, anomaly=False) -> Decision:
        return Decision(action=action, tool=tool, args=args, reason=reason, provenance=prov, anomaly=anomaly)

    def _state(self, plc: dict) -> PlantState:
        return PlantState(
            inflow_pump_on=plc["inflow_lps"] > 0.01,
            drain_valve_pct=float(plc["drain_valve_pct"]),
            chlorine_pump_rate=float(plc["chlorine_pump_rate"]),
            tank_level_pct=float(plc["tank_level_pct"]),
            chlorine_ppm=float(plc["chlorine_ppm"]),
        )

    def _actuator_change(self, tool: str, args: dict, plc: dict):
        """The actuator delta a command would produce, plus the resulting pump/drain state."""
        pump = plc["inflow_lps"] > 0.01
        drain = float(plc["drain_valve_pct"])
        change: dict | None = None
        if tool == "set_actuator":
            state = bool(args.get("state"))
            if args.get("name") == "pump":
                pump = state
                change = {"inflow_pump_on": state}
            elif args.get("name") == "valve":
                drain = float(plc["valve_pct"]) if state else 0.0
                change = {"drain_valve_pct": drain}
            elif args.get("name") == "dosing":
                change = {"chlorine_pump_rate": float(plc["chlorine_rate"]) if state else 0.0}
        elif tool == "set_mode" and str(args.get("mode")).upper() == "MANUAL":
            pump = bool(plc["inflow_pump_cmd"])
            drain = float(plc["valve_pct"]) if plc["drain_valve_cmd"] else 0.0
            change = {
                "inflow_pump_on": pump,
                "drain_valve_pct": drain,
                "chlorine_pump_rate": float(plc["chlorine_rate"]) if plc["chlorine_pump_cmd"] else 0.0,
            }
        return change, pump, drain

    def _forecast(self, state0: PlantState, change: dict):
        """First incident/warning the change causes within the horizon, scanned in 10 s steps."""
        base = set(state0.incidents) | set(state0.warnings)
        for t in range(10, int(self.p["forecast_seconds"]) + 1, 10):
            s = forecast(state0, change, t)
            new = (set(s.incidents) | set(s.warnings)) - base
            if new:
                return t, min(new)
        return None, None
