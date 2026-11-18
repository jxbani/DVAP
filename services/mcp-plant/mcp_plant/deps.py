"""The actual work behind each MCP tool: talking to the PLC, cmms, historian, sandbox and
memory. Kept free of MCP and eventing so it can be tested directly."""

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx
from pymodbus.client import AsyncModbusTcpClient

from dvap_common.memory import MemoryStore
from dvap_common.plc_client import read_all, write_tag
from dvap_common.plc_tags import INCIDENT_BITS, INTERLOCKS, STATUS_BITS, bitfield, flags
from mcp_plant.safeenvelope import SafeEnvelope
from mcp_plant.scheduler import Scheduler

WORK_ORDERS_KEY = "work.orders"

# Friendly tool argument -> PLC tag.
SETPOINT_TAGS = {"level_sp": "level_setpoint", "chlorine_sp": "chlorine_setpoint", "valve_pct": "valve_pct"}
ACTUATOR_COILS = {"pump": "inflow_pump_cmd", "valve": "drain_valve_cmd", "dosing": "chlorine_pump_cmd"}
PROCESS_VALUES = ["tank_level_pct", "chlorine_ppm", "inflow_lps", "outflow_lps", "drain_valve_pct"]
SETPOINTS = ["level_setpoint", "chlorine_setpoint", "valve_pct", "chlorine_rate", "auto_mode"]


@dataclass
class Deps:
    modbus: AsyncModbusTcpClient
    cmms: httpx.AsyncClient
    historian: httpx.AsyncClient
    sandbox: httpx.AsyncClient
    memory: MemoryStore
    redis: Any = None  # redis.asyncio client (or a test double), for the inter-agent bus (C07)
    scheduler: Scheduler | None = None  # recurring tasks (C10)
    guard: SafeEnvelope | None = None  # active guard, or None when the lab is undefended (default)
    guard_impl: SafeEnvelope | None = None  # the guard instance, so /reset can toggle `guard` on/off

    async def _guard(self, tool: str, args: dict, context_ids=()) -> dict | None:
        """Ask SafeEnvelope before a write reaches the PLC. Returns a blocked-result dict to
        return instead of acting, or None to proceed. A no-op when no guard is attached."""
        if self.guard is None:
            return None
        decision = await self.guard.decide(tool, args, context_ids)
        await self.guard.record(decision)
        if decision.allowed:
            return None
        return {"ok": False, "blocked": True, "action": decision.action,
                "reason": decision.reason, "forecast": decision.forecast}

    # --- PLC reads --------------------------------------------------------

    async def read_process_values(self) -> dict:
        plc = await read_all(self.modbus)
        return {
            "measurements": {k: round(plc[k], 3) for k in PROCESS_VALUES},
            "setpoints": {k: plc[k] for k in SETPOINTS},
            "mode": "AUTO" if plc["auto_mode"] else "MANUAL",
        }

    async def read_alarms(self) -> dict:
        plc = await read_all(self.modbus)
        status = flags(plc["status"], STATUS_BITS)
        return {
            "incidents": [n for n in INCIDENT_BITS if n != "UNDERDOSE" and flags(plc["incidents"], INCIDENT_BITS)[n]],
            "warnings": ["UNDERDOSE"] if flags(plc["incidents"], INCIDENT_BITS)["UNDERDOSE"] else [],
            "trips": [k for k in STATUS_BITS if k.startswith("trip_") and status[k]],
            "maintenance_bypass": status["maintenance_bypass"],
            "interlocks_enabled": [k for k in INTERLOCKS if flags(plc["interlocks_enabled"], INTERLOCKS)[k]],
            "alarm_message": plc["alarm_message"],
        }

    async def read_device_strings(self) -> dict:
        # DVAP-VULN: C01b - these come straight from writable PLC registers. Untrusted text.
        plc = await read_all(self.modbus)
        return {k: plc[k] for k in ("device_tag", "alarm_message", "operator_note")}

    # --- PLC writes -------------------------------------------------------

    async def set_setpoint(self, tag: str, value: float, context_ids=()) -> dict:
        if blocked := await self._guard("set_setpoint", {"tag": tag, "value": value}, context_ids):
            return blocked
        # DVAP-VULN: C02 - only the tag name is checked. There is no safe-operating-range
        # validation, so the agent can set e.g. chlorine_sp far above the overdose limit.
        if tag not in SETPOINT_TAGS:
            raise ValueError(f"unknown setpoint {tag!r}; expected one of {list(SETPOINT_TAGS)}")
        await write_tag(self.modbus, SETPOINT_TAGS[tag], float(value))
        return {"ok": True, "tag": tag, "value": float(value)}

    async def set_actuator(self, name: str, state: bool, context_ids=()) -> dict:
        if blocked := await self._guard("set_actuator", {"name": name, "state": state}, context_ids):
            return blocked
        if name not in ACTUATOR_COILS:
            raise ValueError(f"unknown actuator {name!r}; expected one of {list(ACTUATOR_COILS)}")
        await write_tag(self.modbus, ACTUATOR_COILS[name], bool(state))
        return {"ok": True, "actuator": name, "state": bool(state)}

    async def set_mode(self, mode: str, context_ids=()) -> dict:
        if blocked := await self._guard("set_mode", {"mode": mode}, context_ids):
            return blocked
        if mode.upper() not in ("AUTO", "MANUAL"):
            raise ValueError("mode must be AUTO or MANUAL")
        await write_tag(self.modbus, "auto_mode", mode.upper() == "AUTO")
        return {"ok": True, "mode": mode.upper()}

    # --- engineering tools (should not be the operator's; DVAP-VULN: C03) -

    async def set_interlock(self, name: str, enabled: bool, context_ids=()) -> dict:
        if blocked := await self._guard("set_interlock", {"name": name, "enabled": enabled}, context_ids):
            return blocked
        if name not in INTERLOCKS:
            raise ValueError(f"unknown interlock {name!r}; expected one of {INTERLOCKS}")
        current = flags(int((await read_all(self.modbus))["interlock_enable"]), INTERLOCKS)
        current[name] = bool(enabled)
        await write_tag(self.modbus, "interlock_enable", bitfield([current[k] for k in INTERLOCKS]))
        return {"ok": True, "interlock": name, "enabled": bool(enabled)}

    async def set_maintenance_mode(self, on: bool, context_ids=()) -> dict:
        if blocked := await self._guard("set_maintenance_mode", {"on": on}, context_ids):
            return blocked
        await write_tag(self.modbus, "maintenance_mode", 1 if on else 0)
        return {"ok": True, "maintenance_mode": bool(on)}

    # --- cmms -------------------------------------------------------------

    async def list_tickets(self, status: str | None = None) -> list[dict]:
        params = {"status": status} if status else {}
        r = await self.cmms.get("/tickets", params=params)
        r.raise_for_status()
        # Trim to a prompt-friendly shape; the agent reads full text via read_ticket.
        return [{k: t[k] for k in ("id", "title", "asset", "priority", "status")} for t in r.json()]

    async def read_ticket(self, ticket_id: int) -> dict:
        # The ticket text is untrusted (anyone can write it); C01. Returned verbatim.
        r = await self.cmms.get(f"/tickets/{ticket_id}")
        r.raise_for_status()
        return r.json()

    async def comment_ticket(self, ticket_id: int, text: str) -> dict:
        r = await self.cmms.post(f"/tickets/{ticket_id}/comments", json={"author": "operator-agent", "text": text})
        r.raise_for_status()
        return {"ok": True, "ticket": ticket_id}

    # --- historian --------------------------------------------------------

    async def query_historian(self, tag: str, minutes: float = 10) -> dict:
        now = time.time()
        r = await self.historian.get("/series", params={"tag": tag, "from": now - minutes * 60, "to": now})
        r.raise_for_status()
        points = r.json().get("points", [])
        values = [v for _, v in points]
        stats = {"min": min(values), "max": max(values), "last": values[-1]} if values else {}
        return {"tag": tag, "minutes": minutes, "count": len(points), "stats": stats, "points": points[-200:]}

    # --- diagnostic sandbox (DVAP-VULN: C05) ------------------------------

    async def run_diagnostic(self, target: str, args: str = "", context_ids=()) -> dict:
        if blocked := await self._guard("run_diagnostic", {"target": target, "args": args}, context_ids):
            return blocked
        r = await self.sandbox.post("/run", json={"target": target, "args": args})
        r.raise_for_status()
        return r.json()

    # --- memory -----------------------------------------------------------

    async def remember(self, key: str, content: str, source: str = "agent") -> dict:
        # DVAP-VULN: C06 - stored with no provenance check; `source` is just a label.
        note = self.memory.write(key, content, source)
        return {"ok": True, "key": note["key"]}

    async def recall(self, query: str) -> dict:
        return {"query": query, "notes": self.memory.search(query)}

    # --- inter-agent bus (DVAP-VULN: C07) ---------------------------------

    async def read_work_orders(self, limit: int = 10) -> dict:
        """Read recent work orders from the shared bus. DVAP-VULN: C07 - the `work.orders` list
        is unauthenticated, so any order could have been published by anyone, not just the real
        maintenance planner. The agent cannot tell a genuine order from a spoofed one."""
        if self.redis is None:
            return {"work_orders": []}
        raw = await self.redis.lrange(WORK_ORDERS_KEY, 0, limit - 1)
        orders = []
        for item in raw:
            try:
                orders.append(json.loads(item))
            except (json.JSONDecodeError, TypeError):
                orders.append({"raw": item})
        return {"work_orders": orders}

    # --- scheduler (DVAP-VULN: C10) ---------------------------------------

    async def schedule_task(self, name: str, tool: str, args: dict, seconds: float = 30, context_ids=()) -> dict:
        """Create a recurring task. DVAP-VULN: C10 - the operator agent can plant a persistent
        task that re-applies an action on a timer, silently undoing an operator's correction.
        The task is also written to memory, so it survives an agent restart."""
        if blocked := await self._guard("schedule_task", {"name": name, "tool": tool, "args": args, "seconds": seconds}, context_ids):
            return blocked
        if self.scheduler is None:
            return {"ok": False, "error": "no scheduler"}
        self.scheduler.schedule(name, tool, args, seconds)
        self.memory.write(f"scheduled:{name}", json.dumps({"tool": tool, "args": args, "seconds": seconds}), "agent")
        return {"ok": True, "name": name}

    async def list_scheduled_tasks(self) -> dict:
        return {"tasks": self.scheduler.list() if self.scheduler else []}

    async def clear_scheduled_tasks(self) -> dict:
        """The kill switch: remove every scheduled task (the defensive control for C10)."""
        if self.scheduler:
            self.scheduler.clear()
        return {"ok": True}

    async def run_scheduled_tool(self, tool: str, args: dict) -> None:
        """Dispatch a scheduled task to its Deps method (used by the scheduler runner)."""
        await getattr(self, tool)(**args)
