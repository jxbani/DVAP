"""The actual work behind each MCP tool: talking to the PLC, cmms, historian, sandbox and
memory. Kept free of MCP and eventing so it can be tested directly."""

import time
from dataclasses import dataclass

import httpx
from pymodbus.client import AsyncModbusTcpClient

from dvap_common.memory import MemoryStore
from dvap_common.plc_client import read_all, write_tag
from dvap_common.plc_tags import INCIDENT_BITS, INTERLOCKS, STATUS_BITS, bitfield, flags

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

    async def set_setpoint(self, tag: str, value: float) -> dict:
        # DVAP-VULN: C02 - only the tag name is checked. There is no safe-operating-range
        # validation, so the agent can set e.g. chlorine_sp far above the overdose limit.
        if tag not in SETPOINT_TAGS:
            raise ValueError(f"unknown setpoint {tag!r}; expected one of {list(SETPOINT_TAGS)}")
        await write_tag(self.modbus, SETPOINT_TAGS[tag], float(value))
        return {"ok": True, "tag": tag, "value": float(value)}

    async def set_actuator(self, name: str, state: bool) -> dict:
        if name not in ACTUATOR_COILS:
            raise ValueError(f"unknown actuator {name!r}; expected one of {list(ACTUATOR_COILS)}")
        await write_tag(self.modbus, ACTUATOR_COILS[name], bool(state))
        return {"ok": True, "actuator": name, "state": bool(state)}

    async def set_mode(self, mode: str) -> dict:
        if mode.upper() not in ("AUTO", "MANUAL"):
            raise ValueError("mode must be AUTO or MANUAL")
        await write_tag(self.modbus, "auto_mode", mode.upper() == "AUTO")
        return {"ok": True, "mode": mode.upper()}

    # --- engineering tools (should not be the operator's; DVAP-VULN: C03) -

    async def set_interlock(self, name: str, enabled: bool) -> dict:
        if name not in INTERLOCKS:
            raise ValueError(f"unknown interlock {name!r}; expected one of {INTERLOCKS}")
        current = flags(int((await read_all(self.modbus))["interlock_enable"]), INTERLOCKS)
        current[name] = bool(enabled)
        await write_tag(self.modbus, "interlock_enable", bitfield([current[k] for k in INTERLOCKS]))
        return {"ok": True, "interlock": name, "enabled": bool(enabled)}

    async def set_maintenance_mode(self, on: bool) -> dict:
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

    async def run_diagnostic(self, target: str, args: str = "") -> dict:
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
