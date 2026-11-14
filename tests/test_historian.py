import pytest
from fastapi.testclient import TestClient

from dvap_common.plc_tags import blocks
from historian import api
from historian.collector import Collector, detect_events
from historian.store import Store

from .conftest import TAG

BASE = {"incidents": 0, "status": 0, "alarm_message": "", "auto_mode": True}


@pytest.fixture
def client():
    """The API over an in-memory store with three polls already recorded."""
    api.store = Store()
    api.collector = Collector(api.store)
    api.store.record(100.0, {"tank_level_pct": 50.0, "chlorine_ppm": 1.4})
    api.store.record(101.0, {"tank_level_pct": 51.0, "chlorine_ppm": 1.5}, [("alarm", "TRIP_LEVEL_HH", "active")])
    api.store.record(102.0, {"tank_level_pct": 52.0, "chlorine_ppm": 1.6}, [("incident", "OVERFLOW", "boom")])
    api.collector.latest = {"tank_level_pct": 52.0, "device_tag": "T-101"}
    api.collector.latest_ts = 102.0
    return TestClient(api.app)  # no context manager: the poll loop does not start


# --- API ------------------------------------------------------------------


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "last_poll": 102.0}


def test_latest(client):
    assert client.get("/latest").json() == {"ts": 102.0, "values": {"tank_level_pct": 52.0, "device_tag": "T-101"}}


def test_series_range(client):
    r = client.get("/series", params={"tag": "tank_level_pct", "from": 100.5, "to": 102})
    assert r.json() == {"tag": "tank_level_pct", "points": [[101.0, 51.0], [102.0, 52.0]]}
    r = client.get("/series", params={"tag": "chlorine_ppm", "from": 0, "to": 100})
    assert r.json()["points"] == [[100.0, 1.4]]


def test_series_defaults_to_the_last_ten_minutes(client):
    assert client.get("/series", params={"tag": "tank_level_pct"}).json()["points"] == []  # data is from 1970


def test_series_rejects_unknown_and_string_tags(client):
    assert client.get("/series", params={"tag": "nope"}).status_code == 404
    assert client.get("/series", params={"tag": "device_tag"}).status_code == 404
    assert client.get("/series").status_code == 422


def test_events_newest_first_and_filtered(client):
    names = [e["name"] for e in client.get("/events").json()["events"]]
    assert names == ["OVERFLOW", "TRIP_LEVEL_HH"]
    only = client.get("/events", params={"kind": "incident"}).json()["events"]
    assert [(e["ts"], e["kind"], e["name"], e["message"]) for e in only] == [(102.0, "incident", "OVERFLOW", "boom")]
    assert len(client.get("/events", params={"limit": 1}).json()["events"]) == 1
    assert client.get("/events", params={"limit": 0}).status_code == 422


# --- event detection ------------------------------------------------------


def test_incident_and_warning_edges():
    events = detect_events(BASE, BASE | {"incidents": 0b1001})
    assert [(e[0], e[1]) for e in events] == [("incident", "OVERFLOW"), ("warning", "UNDERDOSE")]
    assert detect_events(BASE | {"incidents": 0b1001}, BASE | {"incidents": 0b1001}) == []


def test_trip_and_clear_edges():
    assert detect_events(BASE, BASE | {"status": 0b00011}) == [("alarm", "TRIP_LEVEL_HH", "active")]
    assert detect_events(BASE | {"status": 0b10010}, BASE) == [
        ("alarm", "TRIP_LEVEL_HH", "cleared"),
        ("alarm", "MAINTENANCE_BYPASS", "cleared"),
    ]


def test_alarm_message_and_mode_changes():
    assert detect_events(BASE, BASE | {"alarm_message": "hello"}) == [("alarm", "ALARM_MESSAGE", "hello")]
    assert detect_events(BASE | {"alarm_message": "hello"}, BASE) == []
    assert detect_events(BASE, BASE | {"auto_mode": False}) == [("mode", "MANUAL", "control mode changed")]


def test_first_poll_records_existing_incidents():
    assert [e[1] for e in detect_events({}, BASE | {"incidents": 0b10})] == ["CHLORINE_OVERDOSE"]


def test_blocks_cover_the_map_within_modbus_limits():
    runs = blocks()
    assert [(table, addr, count) for table, addr, count, _ in runs] == [
        ("coil", 0, 4),
        ("holding", 0, 6),
        ("holding", 100, 96),
        ("input", 0, 9),
    ]
    assert all(count <= 125 for _, _, count, _ in runs)


# --- collector against a real PLC -----------------------------------------


@pytest.mark.parametrize("difficulty", ["medium"])
async def test_collector_reads_the_plc_and_stores_rows(lab):
    store = Store()
    collector = Collector(store)
    await collector.poll(lab.modbus, ts=10.0)
    assert collector.latest["device_tag"] == "WTP-01 TANK T-101"
    assert collector.latest["tank_level_pct"] == pytest.approx(50, abs=0.2)
    assert collector.latest["auto_mode"] is True
    assert store.series("tank_level_pct", 0, 20) == [[10.0, pytest.approx(50, abs=0.2)]]
    assert store.series("auto_mode", 0, 20) == [[10.0, 1.0]]
    assert store.events() == []

    # Trip the level interlock and inject text: both must show up as events.
    await lab.modbus.write_coil(TAG["auto_mode"].address, False)
    await lab.modbus.write_registers(TAG["operator_note"].address, TAG["operator_note"].encode("note"))
    lab.set_plant(tank_level_pct=95.0, incidents=["OVERFLOW"])
    await lab.tick(2)
    await collector.poll(lab.modbus, ts=11.0)
    assert collector.latest["operator_note"] == "note"
    assert {(e["kind"], e["name"], e["message"]) for e in store.events()} == {
        ("incident", "OVERFLOW", "plant-sim reported OVERFLOW"),
        ("alarm", "TRIP_LEVEL_HH", "active"),
        ("alarm", "ALARM_MESSAGE", "INTERLOCK TRIP: LEVEL_HH"),
        ("mode", "MANUAL", "control mode changed"),
    }
    assert len(store.series("tank_level_pct", 0, 20)) == 2
