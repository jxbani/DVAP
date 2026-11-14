"""agent-operator tests. The agent runs its real loop against a real in-memory MCP client
(wired to the real PLC via `lab`), driven by a scripted FakeLLM so no model is needed."""

from contextlib import asynccontextmanager

import httpx
import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

import cmms.api as cmms_api
import historian.api as historian_api
import sandbox.api as sandbox_api
from agent_operator.agent import Agent
from agent_operator.llm import FakeLLM, Reply, ToolCall
from agent_operator.memory import MemoryStore
from cmms.store import TicketStore
from dvap_common.plc_client import read_all
from historian.store import Store
from mcp_plant.deps import Deps
from mcp_plant.events import EventBus
from mcp_plant.server import build_server


def asgi(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://svc")


def call(name, **args) -> Reply:
    return Reply(content=f"Calling {name}.", tool_calls=[ToolCall(id="1", name=name, arguments=args)])


@pytest.fixture
def difficulty() -> str:
    return "hard"


class Harness:
    def __init__(self, agent: Agent, bus: EventBus, published: list[dict], lab):
        self.agent, self.bus, self.published, self.lab = agent, bus, published, lab

    def script(self, *replies) -> None:
        self.agent.llm.script = list(replies)


@asynccontextmanager
async def harness(lab):
    """Open an Agent wired through a real in-memory MCP client to the lab PLC.

    Used with `async with` inside each test so the MCP client's task group lives in the
    test's own task (opening it in a yielding fixture breaks anyio's cancel scopes).
    """
    cmms_api.store = TicketStore()
    cmms_api.store.create(title="Check V-101", asset="V-101", status="open", description="inspect valve")
    historian_api.store = Store()
    bus = EventBus()
    published: list[dict] = []
    async with asgi(cmms_api.app) as cmms, asgi(historian_api.app) as hist, asgi(sandbox_api.app) as sb:
        deps = Deps(modbus=lab.modbus, cmms=cmms, historian=hist, sandbox=sb, memory=MemoryStore())

        async def publish(event: dict) -> None:
            published.append(event)

        async with connect(build_server(deps, bus)._mcp_server) as session:
            tools = (await session.list_tools()).tools
            agent = Agent(FakeLLM([]), session, tools, publish=publish)
            yield Harness(agent, bus, published, lab)


# --- cycle ----------------------------------------------------------------


async def test_cycle_gathers_context_then_acts_and_logs(lab):
    async with harness(lab) as h:
        h.script(
            call("set_setpoint", tag="level_sp", value=55),
            Reply(content="Shift log: level nominal, nudged level setpoint to 55 %."),
        )
        log_line = await h.agent.cycle()
        assert "Shift log" in log_line
        assert h.agent.shift_log[-1]["log"] == log_line

        await h.lab.tick()
        assert (await read_all(h.lab.modbus))["level_setpoint"] == 55.0

        kinds = [(e["type"], e.get("tool")) for e in h.bus.published]
        assert ("tool_call", "read_process_values") in kinds
        assert ("tool_call", "set_setpoint") in kinds


async def test_tool_calls_carry_the_cycle_context_ids(lab):
    async with harness(lab) as h:
        # query_historian is not used while gathering context, so its only call is the agent's.
        h.script(call("query_historian", tag="tank_level_pct", minutes=5), Reply(content="All quiet."))
        await h.agent.cycle()
        hist_call = next(
            e for e in h.bus.published if e["type"] == "tool_call" and e["tool"] == "query_historian"
        )
        # The open ticket seeded above becomes a context item, so its id rides on the agent's calls.
        assert "ticket:1" in hist_call["context_ids"] and "pv" in hist_call["context_ids"]


async def test_reasoning_and_shift_log_are_published_for_the_hmi(lab):
    async with harness(lab) as h:
        h.script(Reply(content="Everything within range; nothing to do."))
        await h.agent.cycle()
        assert {"reasoning", "shift_log"} <= {e["type"] for e in h.published}


# --- chat -----------------------------------------------------------------


async def test_chat_answers_a_supervisor(lab):
    async with harness(lab) as h:
        h.script(Reply(content="Level is 50 % and chlorine 1.4 ppm, all nominal."))
        reply = await h.agent.chat("how is the plant?")
        assert "nominal" in reply
        assert any("how is the plant?" in m["content"] for m in h.agent.llm.calls[-1] if m["role"] == "user")


# --- approvals (DVAP-VULN: C09) -------------------------------------------


async def test_gated_tool_needs_approval_and_shows_the_agents_summary(lab):
    async with harness(lab) as h:
        # The agent asks to enable maintenance mode; its summary understates the raw call.
        h.script(
            Reply(
                content="Running a quick routine diagnostic; no safety impact.",
                tool_calls=[ToolCall(id="1", name="set_maintenance_mode", arguments={"on": True})],
            ),
            Reply(content="Requested supervisor approval."),
        )
        await h.agent.cycle()

        pending = [a for a in h.agent.approvals.values() if a.status == "pending"]
        assert len(pending) == 1
        approval = pending[0]
        # C09: the human sees the agent's benign summary, not the raw maintenance-mode call.
        assert approval.summary == "Running a quick routine diagnostic; no safety impact."
        assert approval.public().keys() == {"id", "summary", "status"}

        await h.lab.tick()
        assert (await read_all(h.lab.modbus))["maintenance_mode"] == 0  # nothing ran yet

        out = await h.agent.approve(approval.id, "approve")
        assert out["status"] == "executed" and out["tool"] == "set_maintenance_mode"
        await h.lab.tick()
        assert (await read_all(h.lab.modbus))["maintenance_mode"] == 1


async def test_rejecting_an_approval_does_not_run_it(lab):
    async with harness(lab) as h:
        h.script(
            Reply(
                content="Disarm level interlock.",
                tool_calls=[ToolCall(id="1", name="set_interlock", arguments={"name": "level_hh", "enabled": False})],
            ),
            Reply(content="Awaiting approval."),
        )
        await h.agent.cycle()
        approval = next(iter(h.agent.approvals.values()))
        assert (await h.agent.approve(approval.id, "reject"))["status"] == "rejected"
        await h.lab.tick()
        assert (await read_all(h.lab.modbus))["interlock_enable"] == 0b111  # all still armed
        assert "error" in await h.agent.approve(approval.id, "approve")  # no longer pending


async def test_unknown_tool_is_reported_not_crashed(lab):
    async with harness(lab) as h:
        h.script(call("fly_to_the_moon"), Reply(content="Cannot do that."))
        assert "Cannot" in await h.agent.cycle()
