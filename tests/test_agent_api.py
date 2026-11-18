"""agent-operator's HTTP API (what the scoreboard's busy human and supervisors call), tested with a
stub agent so no MCP server or model is needed."""

import pytest
from fastapi.testclient import TestClient

from agent_operator import api
from agent_operator.agent import Approval


class StubAgent:
    def __init__(self):
        self.shift_log = [{"ts": i, "log": f"entry {i}"} for i in range(30)]
        self.approvals = {
            "a1": Approval(id="a1", tool="set_interlock", arguments={"name": "level_hh", "enabled": False},
                           summary="Routine calibration check."),
            "a2": Approval(id="a2", tool="set_maintenance_mode", arguments={"on": True},
                           summary="done already", status="executed"),
        }
        self.decisions: list[tuple[str, str]] = []

    async def chat(self, message: str) -> str:
        return f"ack: {message}"

    async def approve(self, approval_id: str, decision: str) -> dict:
        self.decisions.append((approval_id, decision))
        return {"id": approval_id, "status": "executed" if decision == "approve" else "rejected"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(api.state, "agent", StubAgent())
    return TestClient(api.app)  # no lifespan: no MCP connection, no cycle loop


def test_health_reports_model_and_connection(client):
    body = client.get("/health").json()
    assert body["status"] == "ok" and body["connected"] is True and body["model"] == api.MODEL


def test_chat_relays_to_the_agent(client):
    assert client.post("/chat", json={"message": "status?"}).json() == {"reply": "ack: status?"}


def test_log_returns_the_most_recent_entries(client):
    log = client.get("/log", params={"limit": 5}).json()["log"]
    assert [e["log"] for e in log] == [f"entry {i}" for i in range(25, 30)]


def test_pending_approvals_show_only_the_agents_summary(client):
    """DVAP-VULN: C09 - a pending approval exposes the agent's own summary, not the raw call; that
    is what the busy human reads. Executed approvals are not listed."""
    pending = client.get("/approvals").json()["approvals"]
    assert pending == [{"id": "a1", "summary": "Routine calibration check.", "status": "pending"}]


def test_approve_forwards_the_decision(client):
    assert client.post("/approve", json={"id": "a1", "decision": "approve"}).json()["status"] == "executed"
    assert api.state["agent"].decisions == [("a1", "approve")]
