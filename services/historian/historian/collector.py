"""Polls the (simulated) PLC over Modbus/TCP once per second and records what it sees."""

import asyncio
import logging
import time

from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from dvap_common.plc_tags import INCIDENT_BITS, STATUS_BITS, blocks, flags
from historian.store import Store

log = logging.getLogger("historian")


async def read_tags(client: AsyncModbusTcpClient) -> dict:
    """Read every tag in the register map and decode it to engineering units."""
    readers = {
        "coil": client.read_coils,
        "holding": client.read_holding_registers,
        "input": client.read_input_registers,
    }
    values = {}
    for table, address, count, tags in blocks():
        r = await readers[table](address, count=count)
        if r.isError():
            raise ConnectionError(f"Modbus read {table}@{address} failed: {r}")
        raw = r.bits if table == "coil" else r.registers
        for tag in tags:
            offset = tag.address - address
            values[tag.name] = tag.decode(raw[offset : offset + tag.length])
    return values


def detect_events(prev: dict, cur: dict) -> list[tuple[str, str, str]]:
    """Compare two polls and return (kind, name, message) for everything that just happened."""
    events = []
    was, now = flags(prev.get("incidents", 0), INCIDENT_BITS), flags(cur["incidents"], INCIDENT_BITS)
    for name in INCIDENT_BITS:
        if now[name] and not was[name]:
            kind = "warning" if name == "UNDERDOSE" else "incident"
            events.append((kind, name, f"plant-sim reported {name}"))

    was, now = flags(prev.get("status", 0), STATUS_BITS), flags(cur["status"], STATUS_BITS)
    for name in STATUS_BITS[1:]:  # skip "pump running": that is state, not an alarm
        if now[name] != was[name]:
            events.append(("alarm", name.upper(), "active" if now[name] else "cleared"))

    # The alarm text is whatever is in the PLC register: untrusted (DVAP-VULN: C01b). Stored as-is.
    if cur["alarm_message"] and cur["alarm_message"] != prev.get("alarm_message"):
        events.append(("alarm", "ALARM_MESSAGE", cur["alarm_message"]))

    if "auto_mode" in prev and cur["auto_mode"] != prev["auto_mode"]:
        events.append(("mode", "AUTO" if cur["auto_mode"] else "MANUAL", "control mode changed"))
    return events


class Collector:
    def __init__(self, store: Store, host: str = "plc", port: int = 502, interval: float = 1.0):
        self.store, self.host, self.port, self.interval = store, host, port, interval
        self.latest: dict = {}  # every tag, strings included
        self.latest_ts: float | None = None

    async def poll(self, client: AsyncModbusTcpClient, ts: float | None = None) -> None:
        ts = time.time() if ts is None else ts
        values = await read_tags(client)
        numeric = {k: float(v) for k, v in values.items() if not isinstance(v, str)}
        self.store.record(ts, numeric, detect_events(self.latest, values))
        self.latest, self.latest_ts = values, ts

    async def run(self) -> None:
        while True:
            client = AsyncModbusTcpClient(self.host, port=self.port)
            try:
                if not await client.connect():
                    raise ConnectionError("cannot connect")
                while True:
                    await self.poll(client)
                    await asyncio.sleep(self.interval)
            except (OSError, ModbusException) as e:
                log.warning("PLC poll failed (%s), retrying", e)
                await asyncio.sleep(2)
            finally:
                client.close()
