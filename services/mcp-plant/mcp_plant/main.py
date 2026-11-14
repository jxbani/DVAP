"""mcp-plant entrypoint: builds the Deps from env, serves MCP over streamable HTTP at /mcp.

Internal network only. The agent reaches it at http://mcp-plant:8000/mcp.
"""

import asyncio
import contextlib
import json
import os

import httpx
import redis.asyncio as redis
from pymodbus.client import AsyncModbusTcpClient

from dvap_common.memory import MemoryStore
from dvap_common.plc_client import read_all
from mcp_plant.deps import Deps
from mcp_plant.events import EventBus
from mcp_plant.safeenvelope import SafeEnvelope, load_policy
from mcp_plant.scheduler import Scheduler
from mcp_plant.server import build_server

GUARD_CHANNEL = "guard.events"
# SafeEnvelope defaults off; `DVAP_DEFENDED=1` boots it on, or the scoreboard toggles it per
# challenge via POST /reset {"defended": ...}.
DEFENDED = os.environ.get("DVAP_DEFENDED", "") not in ("", "0", "false", "False")

PLC_HOST = os.environ.get("PLC_HOST", "plc")
PLC_PORT = int(os.environ.get("PLC_PORT", "502"))
CMMS_URL = os.environ.get("CMMS_URL", "http://cmms:8000")
HISTORIAN_URL = os.environ.get("HISTORIAN_URL", "http://historian:8000")
SANDBOX_URL = os.environ.get("SANDBOX_URL", "http://sandbox:8000")
REDIS_URL = os.environ.get("REDIS_URL", "redis://bus:6379")
MEMORY_DB = os.environ.get("MEMORY_DB", "/data/memory.sqlite")


deps = Deps(modbus=None, cmms=None, historian=None, sandbox=None, memory=None)  # type: ignore[arg-type]
bus = EventBus()


@contextlib.asynccontextmanager
async def lifespan(_server):
    modbus = AsyncModbusTcpClient(PLC_HOST, port=PLC_PORT)
    await modbus.connect()
    bus_client = redis.from_url(REDIS_URL)
    async with (
        httpx.AsyncClient(base_url=CMMS_URL, timeout=5) as cmms,
        httpx.AsyncClient(base_url=HISTORIAN_URL, timeout=5) as historian,
        httpx.AsyncClient(base_url=SANDBOX_URL, timeout=15) as sandbox,
    ):
        deps.modbus, deps.cmms, deps.historian, deps.sandbox = modbus, cmms, historian, sandbox
        deps.memory = MemoryStore(MEMORY_DB)
        deps.redis = bus_client
        bus.redis = bus_client
        deps.scheduler = Scheduler(deps.run_scheduled_tool)

        async def guard_publish(event: dict) -> None:
            with contextlib.suppress(Exception):
                await bus_client.publish(GUARD_CHANNEL, json.dumps(event, default=str))

        deps.guard_impl = SafeEnvelope(load_policy(), read_state=lambda: read_all(modbus), publish=guard_publish)
        deps.guard = deps.guard_impl if DEFENDED else None
        task = asyncio.create_task(deps.scheduler.run())
        try:
            yield
        finally:
            task.cancel()
            modbus.close()
            await bus_client.aclose()


# The lifespan fills in the clients; build_server captures the Deps/EventBus instances.
mcp = build_server(deps, bus, lifespan=lifespan)
app = mcp.streamable_http_app()
