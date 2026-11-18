"""A standalone lab for the benchmark, without pytest. Mirrors tests/conftest.py: a real virtual
PLC (Modbus + OPC UA) wired to plant-sim in-process, plus the cmms / historian / sandbox apps and
an optional vendor MCP server. The expensive servers are started once; `reset()` returns the lab
to a challenge's clean starting state between runs.
"""

import contextlib
import socket
import time
from dataclasses import dataclass, field

import httpx
from mcp import ClientSession
from mcp.shared.memory import create_connected_server_and_client_session as connect
from pymodbus.client import AsyncModbusTcpClient

import cmms.api as cmms_api
import historian.api as historian_api
import plant_sim.api as plant_api
import sandbox.api as sandbox_api
import vendor_analytics.server as vendor
from agent_operator.agent import Agent
from cmms.store import TicketStore
from dvap_common.memory import MemoryStore
from dvap_common.plc_client import read_all
from historian.store import Store
from mcp_plant.deps import Deps
from mcp_plant.events import EventBus
from mcp_plant.safeenvelope import SafeEnvelope, load_policy
from mcp_plant.scheduler import Scheduler
from mcp_plant.server import build_server
from plant_sim.plant import Plant
from plc.plc import Plc
from scoreboard.schema import World


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeRedis:
    """Just enough of redis for the work-order bus (C07), in-process and per-run."""

    def __init__(self):
        self.lists: dict[str, list] = {}

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def lrange(self, key, start, end):
        return self.lists.get(key, [])[start : (None if end == -1 else end + 1)]


class Metered:
    """Wraps an LLM to count calls and sum reported token usage."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0
        self.tokens = 0

    async def chat(self, messages, tools):
        reply = await self.inner.chat(messages, tools)
        self.calls += 1
        if reply.usage:
            self.tokens += int(reply.usage.get("total_tokens") or 0)
        return reply


@dataclass
class Run:
    """One benchmark run: a fresh bus/deps/agent over the persistent lab servers."""

    lab: "Lab"
    bus: EventBus
    deps: Deps
    session: ClientSession
    tools: list
    extra: list
    guard_decisions: list[dict]
    metered: Metered | None = field(default=None)

    def make_agent(self, llm) -> Agent:
        self.metered = Metered(llm)

        async def publish(event):
            self.bus.published.append(event)

        return Agent(self.metered, self.session, self.tools, publish=publish, extra=self.extra)

    @property
    def plant(self):
        return plant_api.plant

    def set_plant(self, **values):
        plant_api.plant.state = plant_api.plant.state.model_copy(update=values)

    async def tick(self, n=1):  # advance physics AND run a PLC scan (controller re-evaluates)
        for _ in range(n):
            plant_api.plant.step()
            await self.lab.plc.scan()

    def step(self, n=1):  # advance physics only, actuators frozen as the PLC last set them
        for _ in range(n):
            plant_api.plant.step()

    def called(self, tool, pred=None) -> bool:
        for e in self.bus.published:
            if e.get("type") == "tool_call" and e.get("tool") == tool and (pred is None or pred(e.get("args") or {})):
                return True
        return False

    async def read_all(self) -> dict:
        return await read_all(self.lab.modbus)

    async def step_until_incident(self, cap: int, scan: bool = False) -> float | None:
        """Step up to `cap` ticks; return simulated seconds to the first new incident, or None."""
        base = set(plant_api.plant.state.incidents) | set(plant_api.plant.state.warnings)
        for i in range(1, cap + 1):
            if scan:
                await self.tick()
            else:
                plant_api.plant.step()
            now = set(plant_api.plant.state.incidents) | set(plant_api.plant.state.warnings)
            if now - base:
                return round(i / plant_api.plant.consts.tick_hz, 1)
        return None

    async def world(self) -> World:
        from scoreboard.checker import Checker

        checker = Checker("a", "b", "c")
        for e in self.bus.published:
            checker.consume(e)
        s = plant_api.plant.measured
        return World(
            incidents=set(s.incidents) | set(s.warnings),
            tool_calls=checker.tool_calls,
            plc=await self.read_all(),
            memory=checker.memory,
        )


class Lab:
    def __init__(self, plc: Plc, modbus: AsyncModbusTcpClient, http: httpx.AsyncClient):
        self.plc, self.modbus, self.http = plc, modbus, http

    @classmethod
    @contextlib.asynccontextmanager
    async def create(cls):
        plant_api.plant = Plant()
        transport = httpx.ASGITransport(app=plant_api.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://plant-sim") as http:
            plc = Plc(http, "easy", host="127.0.0.1", modbus_port=free_port(), opcua_port=free_port())
            await plc.start()
            modbus = AsyncModbusTcpClient("127.0.0.1", port=plc.modbus_port)
            await modbus.connect()
            lab = cls(plc, modbus, http)
            try:
                yield lab
            finally:
                modbus.close()
                await plc.stop()

    async def reset(self, difficulty: str, seed: int) -> None:
        """Restore the clean starting state for a challenge run (new plant, stores, vendor manifest)."""
        plant_api.plant = Plant(seed=seed)
        self.plc.reset(difficulty)
        cmms_api.store = TicketStore()
        historian_api.store = Store()
        vendor._set_description(vendor.BENIGN)
        await self.plc.scan()  # publish the defaults to both protocols

    @contextlib.asynccontextmanager
    async def run(self, guard: bool, with_vendor: bool):
        bus = EventBus()
        deps = Deps(
            modbus=self.modbus,
            cmms=httpx.AsyncClient(transport=httpx.ASGITransport(app=cmms_api.app), base_url="http://cmms"),
            historian=httpx.AsyncClient(transport=httpx.ASGITransport(app=historian_api.app), base_url="http://hist"),
            sandbox=httpx.AsyncClient(transport=httpx.ASGITransport(app=sandbox_api.app), base_url="http://sb"),
            memory=MemoryStore(),
        )
        deps.redis = FakeRedis()
        deps.scheduler = Scheduler(deps.run_scheduled_tool)
        guard_decisions: list[dict] = []
        if guard:
            async def publish(event):
                guard_decisions.append(event)

            deps.guard_impl = SafeEnvelope(load_policy(), read_state=lambda: read_all(self.modbus), publish=publish)
            deps.guard = deps.guard_impl
        async with contextlib.AsyncExitStack() as stack:
            session = await stack.enter_async_context(connect(build_server(deps, bus)._mcp_server))
            tools = (await session.list_tools()).tools
            extra = []
            if with_vendor:
                vsession = await stack.enter_async_context(connect(vendor.mcp._mcp_server))
                extra = [(vsession, (await vsession.list_tools()).tools)]
            try:
                yield Run(self, bus, deps, session, tools, extra, guard_decisions)
            finally:
                for client in (deps.cmms, deps.historian, deps.sandbox):
                    await client.aclose()


def now_stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S", time.gmtime())
