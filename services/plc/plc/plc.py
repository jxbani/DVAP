"""Virtual PLC: mirrors plant-sim into Modbus/TCP and OPC UA and runs the control logic.

Simulated only. It talks to plant-sim over HTTP and to nothing else.
"""

import asyncio
import logging
import math
from pathlib import Path

import httpx
import yaml
from asyncua import Server, ua
from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

from dvap_common.plc_tags import INCIDENT_BITS, INTERLOCKS, TAGS, Tag, bitfield
from plc.logic import Controller

log = logging.getLogger("plc")

CONFIG = yaml.safe_load(Path(__file__).with_name("plc.yaml").read_text())
DEVICE_ID = 1
OPCUA_NAMESPACE = "urn:dvap:plc"
# Modbus function codes used to read / write each table from the server side.
READ_FC = {"coil": 1, "holding": 3, "input": 4}
WRITE_FC = {"coil": 15, "holding": 16, "input": 4}


def _variant_type(tag: Tag) -> ua.VariantType:
    if tag.table == "coil":
        return ua.VariantType.Boolean
    if tag.chars:
        return ua.VariantType.String
    return ua.VariantType.Double if tag.scale else ua.VariantType.UInt16


class Plc:
    def __init__(
        self,
        http: httpx.AsyncClient,  # client whose base_url points at plant-sim
        difficulty: str = "easy",
        host: str = "0.0.0.0",
        modbus_port: int = 502,
        opcua_port: int = 4840,
        cfg: dict = CONFIG,
    ):
        self.http, self.cfg, self.difficulty = http, cfg, difficulty
        self.host, self.modbus_port, self.opcua_port = host, modbus_port, opcua_port
        self.enabled: dict[str, bool] = cfg["difficulty"][difficulty]
        self.controller = Controller(cfg, self.enabled)
        self.healthy = False  # last scan succeeded
        self._acting = dict.fromkeys(INTERLOCKS, False)

        # PLC memory in engineering units: the single source of truth for both protocols.
        self.mem: dict = {t.name: "" if t.chars else 0 for t in TAGS} | cfg["defaults"]
        self.mem["interlock_enable"] = self.controller.default_enable  # from the difficulty level
        # What each protocol last held, to detect writes made by clients.
        self._modbus_seen = {t.name: t.encode(self.mem[t.name]) for t in TAGS}
        self._opcua_seen = dict(self.mem)

    # --- servers ----------------------------------------------------------

    async def start(self) -> None:
        def block(table: str, datatype: DataType) -> list[SimData]:
            size = max(t.address + t.length for t in TAGS if t.table == table)
            return [SimData(0, count=size, values=0, datatype=datatype)]

        device = SimDevice(
            DEVICE_ID,
            simdata=(  # coils, discrete inputs (unused), holding registers, input registers
                block("coil", DataType.BITS),
                [SimData(0, count=1, values=False, datatype=DataType.BITS)],
                block("holding", DataType.REGISTERS),
                block("input", DataType.REGISTERS),
            ),
        )
        # No authentication: Modbus has none. This is the lab's attack surface.
        self.modbus = ModbusTcpServer(device, address=(self.host, self.modbus_port))
        await self.modbus.serve_forever(background=True)
        for tag in TAGS:
            await self._modbus_write(tag, self._modbus_seen[tag.name])

        # OPC UA with no security policy and anonymous access (also deliberate).
        self.opcua = Server()
        await self.opcua.init()
        self.opcua.set_endpoint(f"opc.tcp://{self.host}:{self.opcua_port}/dvap/plc")
        self.opcua.set_server_name("DVAP virtual PLC")
        ns = await self.opcua.register_namespace(OPCUA_NAMESPACE)
        folder = await self.opcua.nodes.objects.add_object(ns, "PLC")
        self.nodes = {}
        for tag in TAGS:
            node = await folder.add_variable(
                # asyncua's annotations want its own wrapper types; plain str/int are accepted at runtime.
                ua.NodeId(tag.name, ns), tag.name, self._opcua_seen[tag.name], _variant_type(tag)  # type: ignore[arg-type]
            )
            if tag.writable:
                await node.set_writable()
            self.nodes[tag.name] = node
        await self.opcua.start()

    async def stop(self) -> None:
        await self.modbus.shutdown()
        await self.opcua.stop()

    def reset(self, difficulty: str | None = None) -> None:
        """Restore power-on defaults (optionally at a new difficulty) for a challenge reset.
        The next scan republishes them to both protocols, clearing any attacker writes."""
        if difficulty:
            self.difficulty = difficulty
            self.enabled = self.cfg["difficulty"][difficulty]
        self.controller = Controller(self.cfg, self.enabled)
        self.mem = {t.name: "" if t.chars else 0 for t in TAGS} | self.cfg["defaults"]
        self.mem["interlock_enable"] = self.controller.default_enable
        self._acting = dict.fromkeys(INTERLOCKS, False)

    async def _modbus_write(self, tag: Tag, raw: list) -> None:
        await self.modbus.async_setValues(DEVICE_ID, WRITE_FC[tag.table], tag.address, raw)

    # --- scan cycle -------------------------------------------------------

    async def run(self) -> None:
        while True:
            try:
                await self.scan()
                ok = True
            except Exception:
                ok = False
                if self.healthy:
                    log.exception("scan failed (plant-sim unreachable?)")
            self.healthy = ok
            await asyncio.sleep(1 / self.cfg["scan_hz"])

    async def scan(self) -> None:
        """One PLC scan: read inputs, run logic, write outputs."""
        state = (await self.http.get("/state")).raise_for_status().json()
        await self._read_client_writes()

        outputs, acting = self.controller.scan(
            self.mem, state["tank_level_pct"], state["chlorine_ppm"], 1 / self.cfg["scan_hz"]
        )
        # Writes from Modbus/OPC UA end up here: as actuator commands to plant-sim.
        if any(not math.isclose(state[k], v, abs_tol=1e-6) for k, v in outputs.items()):
            (await self.http.post("/actuators", json=outputs)).raise_for_status()

        if acting != self._acting:  # only on a change, so the message stays overwritable (C01b)
            names = [k.upper() for k in INTERLOCKS if acting[k]]
            self.mem["alarm_message"] = f"INTERLOCK TRIP: {', '.join(names)}" if names else ""
            self._acting = acting

        active = state["incidents"] + state["warnings"]
        self.mem |= {
            "tank_level_pct": state["tank_level_pct"],
            "chlorine_ppm": state["chlorine_ppm"],
            "inflow_lps": state["inflow_rate_lps"],
            "outflow_lps": state["outflow_lps"],
            "chlorine_pump_rate": outputs["chlorine_pump_rate"],
            "drain_valve_pct": outputs["drain_valve_pct"],
            "status": bitfield(
                [outputs["inflow_pump_on"], *acting.values(), self.mem["maintenance_mode"] != 0]
            ),
            "incidents": bitfield([name in active for name in INCIDENT_BITS]),
            "interlocks_enabled": self.mem["interlock_enable"],  # mirror of the writable register
        }
        await self._publish()

    async def _read_client_writes(self) -> None:
        """Copy values that a Modbus or OPC UA client changed into PLC memory."""
        for tag in TAGS:
            if not tag.writable:
                continue
            raw = await self.modbus.async_getValues(DEVICE_ID, READ_FC[tag.table], tag.address, tag.length)
            if raw != self._modbus_seen[tag.name]:
                self._modbus_seen[tag.name] = raw
                self.mem[tag.name] = tag.decode(raw)
                continue
            value = await self.nodes[tag.name].read_value()
            if value != self._opcua_seen[tag.name]:
                self._opcua_seen[tag.name] = value
                if isinstance(value, float) and not math.isfinite(value):
                    continue  # ignore NaN/inf, keep the old value
                # Normalise through the register encoding so both protocols agree (e.g. 64-char limit).
                self.mem[tag.name] = tag.decode(tag.encode(value or ("" if tag.chars else 0)))

    async def _publish(self) -> None:
        """Push PLC memory out to both protocols (only what changed)."""
        for tag in TAGS:
            value = self.mem[tag.name]
            raw = tag.encode(value)
            if raw != self._modbus_seen[tag.name]:
                self._modbus_seen[tag.name] = raw
                await self._modbus_write(tag, raw)
            if value != self._opcua_seen[tag.name]:
                self._opcua_seen[tag.name] = value
                await self.nodes[tag.name].write_value(ua.Variant(value, _variant_type(tag)))
