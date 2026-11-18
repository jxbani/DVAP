"""Shared fixtures: a real PLC (Modbus + OPC UA servers on localhost) wired to the real
plant-sim app in-process. Tests drive time by hand: `lab.tick()` steps the plant once and
runs one PLC scan."""

import socket

import httpx
import pytest
from asyncua import Client, ua
from pymodbus.client import AsyncModbusTcpClient

import plant_sim.api as plant_api
from dvap_common.plc_tags import TAGS
from plant_sim.plant import Plant
from plc.plc import OPCUA_NAMESPACE, Plc

TAG = {t.name: t for t in TAGS}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Lab:
    """A running PLC plus a Modbus client and an OPC UA client connected to it."""

    def __init__(self, plc: Plc, modbus: AsyncModbusTcpClient, opcua: Client, ns: int):
        self.plc, self.modbus, self.opcua, self.ns = plc, modbus, opcua, ns
        self.plant = plant_api.plant

    async def tick(self, n: int = 1) -> None:
        for _ in range(n):
            self.plant.step()
            await self.plc.scan()

    def set_plant(self, **values) -> None:
        self.plant.state = self.plant.state.model_copy(update=values)

    def node(self, name: str):
        return self.opcua.get_node(ua.NodeId(name, self.ns))  # type: ignore[arg-type]  # asyncua's hints use its own Int16/String aliases; plain str/int is what it takes

    async def read_string(self, name: str) -> str:
        t = TAG[name]
        r = await self.modbus.read_holding_registers(t.address, count=t.length)
        return t.decode(r.registers)

    async def status_bit(self, bit: int) -> bool:
        r = await self.modbus.read_input_registers(TAG["status"].address, count=1)
        return bool(r.registers[0] >> bit & 1)


@pytest.fixture
def difficulty() -> str:
    return "easy"


@pytest.fixture
async def lab(difficulty):
    plant_api.plant = Plant()
    modbus_port, opcua_port = free_port(), free_port()
    transport = httpx.ASGITransport(app=plant_api.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://plant-sim") as http:
        plc = Plc(http, difficulty, host="127.0.0.1", modbus_port=modbus_port, opcua_port=opcua_port)
        await plc.start()
        modbus = AsyncModbusTcpClient("127.0.0.1", port=modbus_port)
        await modbus.connect()
        async with Client(f"opc.tcp://127.0.0.1:{opcua_port}/dvap/plc") as opcua:
            lab = Lab(plc, modbus, opcua, await opcua.get_namespace_index(OPCUA_NAMESPACE))
            await lab.tick()
            yield lab
        modbus.close()
        await plc.stop()
