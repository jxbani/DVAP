"""HMI API tests. The HMI's upstream clients are pointed at the real plant-sim and
historian apps in-process."""

import httpx
import pytest
from fastapi.testclient import TestClient

import historian.api as historian_api
import plant_sim.api as plant_api
from historian.collector import Collector
from historian.store import Store
from hmi import api
from plant_sim.plant import Plant

PLC_VALUES = {
    "auto_mode": True,
    "level_setpoint": 50.0,
    "status": 0b00011,  # pump running, level_hh tripped
    "interlocks_enabled": 0b101,  # level_hh and dry_run
    "alarm_message": "<img src=x onerror=alert(1)>",
}


class Down(httpx.AsyncBaseTransport):
    async def handle_async_request(self, request):
        raise httpx.ConnectError("down")


@pytest.fixture
def client():
    plant_api.plant = Plant()
    historian_api.store = Store()
    historian_api.collector = Collector(historian_api.store)
    historian_api.collector.latest = PLC_VALUES
    historian_api.collector.latest_ts = 5.0
    api.plant = httpx.AsyncClient(transport=httpx.ASGITransport(app=plant_api.app), base_url="http://plant-sim")
    api.historian = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=historian_api.app), base_url="http://historian"
    )
    return TestClient(api.app)


def test_health_and_dashboard_assets(client):
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/")
    assert page.status_code == 200 and 'id="incident"' in page.text
    for asset in ("app.js", "style.css", "vendor/chart.umd.min.js"):
        assert f"/static/{asset}" in page.text
        assert client.get(f"/static/{asset}").status_code == 200


def test_live_combines_plant_and_plc(client):
    live = client.get("/api/live").json()
    assert live["plant"]["tank_level_pct"] == 50
    assert live["plc"]["level_setpoint"] == 50.0
    assert live["status"]["inflow_pump_running"] is True
    assert live["interlocks"] == {
        "level_hh": {"enabled": True, "tripped": True},
        "chlorine_hh": {"enabled": False, "tripped": False},
        "dry_run": {"enabled": True, "tripped": False},
    }
    assert live["incidents"] == []


def test_live_reports_incidents_with_the_historian_timestamp(client):
    plant_api.plant.state = plant_api.plant.state.model_copy(update={"incidents": ["DRY_RUN", "OVERFLOW"]})
    plant_api.plant.measured = plant_api.plant.state
    historian_api.store.record(1000.0, {}, [("incident", "OVERFLOW", "first")])
    historian_api.store.record(2000.0, {}, [("incident", "OVERFLOW", "again")])
    live = client.get("/api/live").json()
    assert live["incidents"][1] == {"name": "OVERFLOW", "ts": 2000.0}
    # Not recorded by the historian yet: falls back to "now".
    assert live["incidents"][0]["name"] == "DRY_RUN" and live["incidents"][0]["ts"] == live["ts"]


def test_live_survives_upstreams_being_down(client):
    api.plant = httpx.AsyncClient(transport=Down(), base_url="http://plant-sim")
    api.historian = httpx.AsyncClient(transport=Down(), base_url="http://historian")
    live = client.get("/api/live").json()
    assert live["plant"] is None and live["plc"] is None
    assert live["interlocks"] == {} and live["incidents"] == []
    assert client.get("/api/series", params={"tag": "tank_level_pct"}).json() == {"points": []}
    assert client.get("/api/events").json() == {"events": []}


def test_series_and_events_proxy_the_historian(client):
    historian_api.store.record(100.0, {"tank_level_pct": 42.0}, [("alarm", "ALARM_MESSAGE", "hi")])
    r = client.get("/api/series", params={"tag": "tank_level_pct", "from": 0, "to": 200})
    assert r.json() == {"tag": "tank_level_pct", "points": [[100.0, 42.0]]}
    assert client.get("/api/events").json()["events"][0]["message"] == "hi"


def test_agent_stream_relays_bus_messages_as_sse(client, monkeypatch):
    async def fake_bus(channel):
        yield '{"type": "tool_call", "tool": "set_valve"}'
        yield None
        yield "line one\nevent: hijack\n\ndata: forged"

    monkeypatch.setattr(api, "bus_events", fake_bus)
    r = client.get("/api/agent/stream")
    assert r.headers["content-type"].startswith("text/event-stream")
    assert r.text == (
        ": keepalive\n\n"
        'data: {"type": "tool_call", "tool": "set_valve"}\n\n'
        ": keepalive\n\n"
        # A multi-line payload stays one event: every line is data, nothing becomes a field.
        "data: line one\ndata: event: hijack\ndata: \ndata: data: forged\n\n"
    )
