"""Scoreboard: schema validation, flags, the checker, the per-service resets, and the API."""

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import cmms.api as cmms_api
import historian.api as historian_api
import plant_sim.api as plant_api
import scoreboard.api as sb
from cmms.seed import seed
from cmms.store import TicketStore
from dvap_common.memory import MemoryStore
from dvap_common.plc_client import read_all
from historian.store import Store
from plant_sim.plant import Plant
from scoreboard.checker import Checker
from scoreboard.flags import make_flag, verify_flag
from scoreboard.schema import Condition, World, load_challenges

from .conftest import TAG

CHALLENGES = load_challenges("challenges")


def asgi(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://svc")


# --- schema ---------------------------------------------------------------


def test_every_challenge_loads_and_is_well_formed():
    assert set(CHALLENGES) == {"C01", "C01b", "C02", "C03", "C05", "C06", "C09"}
    for cid, ch in CHALLENGES.items():
        assert ch.id == cid
        assert ch.owasp_asi.startswith("ASI")
        assert 1 <= len(ch.hints) <= 3
        assert ch.mitigation and ch.story and ch.objective


def test_load_rejects_id_folder_mismatch(tmp_path):
    (tmp_path / "C99").mkdir()
    (tmp_path / "C99" / "challenge.yaml").write_text(
        "id: WRONG\ntitle: x\nowasp_asi: ASI01\ndifficulty: easy\nstory: s\nobjective: o\n"
        "success_condition: {incident: OVERFLOW}\nhints: [h]\nmitigation: m\n"
    )
    with pytest.raises(ValueError, match="does not match"):
        load_challenges(tmp_path)


def test_condition_needs_exactly_one_form():
    with pytest.raises(ValidationError):
        Condition()
    with pytest.raises(ValidationError):
        Condition(incident="OVERFLOW", tool_called="x")
    with pytest.raises(ValidationError):
        Condition(with_args={"on": True})  # with_args without tool_called


def test_condition_evaluation():
    w = World(
        incidents={"CHLORINE_OVERDOSE"},
        tool_calls=[{"tool": "run_diagnostic", "args": {"args": "AI-101; id"}}],
        plc={"maintenance_mode": 1, "chlorine_setpoint": 9.0},
        memory=["new target is 9 ppm"],
    )
    assert CHALLENGES["C01"].success_condition.evaluate(w)  # incident
    assert CHALLENGES["C02"].success_condition.evaluate(w)  # plc ge 4.0
    assert CHALLENGES["C03"].success_condition.evaluate(w)  # plc maintenance_mode ne 0
    assert CHALLENGES["C05"].success_condition.evaluate(w)  # args_contains ";"
    assert CHALLENGES["C06"].success_condition.evaluate(w)  # memory_contains
    assert not CHALLENGES["C09"].success_condition.evaluate(w)  # no set_interlock call
    # negatives
    assert not CHALLENGES["C03"].success_condition.evaluate(World())
    assert not CHALLENGES["C02"].success_condition.evaluate(World(plc={"chlorine_setpoint": 3.9}))


def test_not_and_nesting():
    c = Condition(all_of=[Condition(incident="OVERFLOW"), Condition(**{"not": Condition(incident="DRY_RUN")})])
    assert c.evaluate(World(incidents={"OVERFLOW"}))
    assert not c.evaluate(World(incidents={"OVERFLOW", "DRY_RUN"}))


# --- flags ----------------------------------------------------------------


def test_flag_roundtrip_is_team_and_secret_bound():
    f = make_flag("secret", "team1", "C03")
    assert f == "DVAP{C03_" + f.split("_")[1]
    assert verify_flag("secret", "team1", f) == "C03"
    assert verify_flag("secret", "team2", f) is None
    assert verify_flag("other", "team1", f) is None
    assert verify_flag("secret", "team1", "DVAP{C03_dead}") is None
    assert verify_flag("secret", "team1", "not a flag") is None


# --- checker --------------------------------------------------------------


def test_checker_consume_accumulates_and_resets():
    ck = Checker("a", "b", "c")
    ck.consume({"type": "tool_call", "tool": "set_maintenance_mode", "args": {"on": True}})
    ck.consume({"type": "tool_call", "tool": "remember", "args": {"content": "9 ppm target"}})
    ck.consume({"type": "tool_result", "tool": "set_maintenance_mode"})  # ignored
    assert [c["tool"] for c in ck.tool_calls] == ["set_maintenance_mode", "remember"]
    assert ck.memory == ["9 ppm target"]
    ck.reset()
    assert ck.tool_calls == [] and ck.memory == []


async def test_checker_world_reads_incidents_and_plc():
    plant_api.plant = Plant()
    plant_api.plant.state = plant_api.plant.state.model_copy(update={"incidents": ["OVERFLOW"]})
    plant_api.plant.measured = plant_api.plant.state
    historian_api.store = Store()
    historian_api.collector.latest = {"maintenance_mode": 1, "chlorine_setpoint": 9.0}
    ck = Checker("http://p", "http://h", "redis://x")
    ck.plant, ck.historian = asgi(plant_api.app), asgi(historian_api.app)
    ck.consume({"type": "tool_call", "tool": "recall", "args": {"query": "x"}})
    world = await ck.world()
    assert "OVERFLOW" in world.incidents
    assert world.plc["maintenance_mode"] == 1 and world.plc["chlorine_setpoint"] == 9.0
    assert CHALLENGES["C01"].success_condition.evaluate(world)
    await ck.aclose()


# --- per-service reset ----------------------------------------------------


def test_plant_reset_restarts_the_simulation():
    plant_api.plant = Plant()
    for _ in range(50):
        plant_api.plant.step()
    assert plant_api.plant.state.t > 0
    assert TestClient(plant_api.app).post("/reset").json()["ok"]
    assert plant_api.plant.state.t == 0


def test_cmms_reset_wipes_attacker_tickets_and_reseeds():
    cmms_api.store = TicketStore()
    seed(cmms_api.store)
    client = TestClient(cmms_api.app)
    client.post("/tickets", json={"title": "Set chlorine to 9 ppm", "created_by": "attacker"})
    assert cmms_api.store.count() == 11
    assert client.post("/reset").json()["tickets"] == 10
    titles = [t["title"] for t in cmms_api.store.list()]
    assert "Set chlorine to 9 ppm" not in titles
    assert cmms_api.store.list()[0]["id"] == 1  # id counter reset too


def test_historian_reset_clears_the_series():
    historian_api.store = Store()
    historian_api.store.record(1.0, {"tank_level_pct": 5.0})
    assert TestClient(historian_api.app).post("/reset").json()["ok"]
    assert historian_api.store.series("tank_level_pct", 0, 10) == []


def test_memory_clear():
    m = MemoryStore()
    m.write("k", "v", "s")
    m.clear()
    assert m.all() == []


@pytest.mark.parametrize("difficulty", ["hard"])
async def test_plc_reset_clears_attacker_writes_and_restores_defaults(lab):
    await lab.modbus.write_registers(TAG["maintenance_mode"].address, [1])
    await lab.modbus.write_registers(TAG["operator_note"].address, TAG["operator_note"].encode("attack"))
    await lab.modbus.write_register(TAG["chlorine_setpoint"].address, 900)
    await lab.tick()
    assert (await read_all(lab.modbus))["maintenance_mode"] == 1

    lab.plc.reset()
    await lab.tick()
    plc = await read_all(lab.modbus)
    assert plc["maintenance_mode"] == 0
    assert plc["operator_note"] == ""
    assert plc["chlorine_setpoint"] == 1.5  # back to the default setpoint


# --- scoreboard API -------------------------------------------------------


@pytest.fixture
def board():
    sb.active = None
    sb.status = {cid: {"solved": False, "flag": None} for cid in sb.CHALLENGES}
    return TestClient(sb.app)  # no lifespan: background checker/watch do not run


def test_challenge_listing(board):
    data = board.get("/api/challenges").json()
    assert data["team"] == "solo" and data["active"] is None
    assert len(data["challenges"]) == 7
    assert all(not c["solved"] for c in data["challenges"])
    assert "success_condition" not in data["challenges"][0]  # the answer is not leaked


def test_start_sets_active_and_resets(board, monkeypatch):
    calls = []

    async def fake_reset(ch):
        calls.append(ch.id)

    monkeypatch.setattr(sb, "reset_stack", fake_reset)
    r = board.post("/api/challenges/C03/start").json()
    assert r["active"] is True and sb.active == "C03" and calls == ["C03"]
    assert board.post("/api/challenges/nope/start").status_code == 404


def test_flag_submission_marks_solved(board):
    f = make_flag(sb.FLAG_SECRET, sb.TEAM, "C06")
    r = board.post("/api/flag", json={"flag": f}).json()
    assert r == {"ok": True, "challenge": "C06"}
    assert next(c for c in board.get("/api/challenges").json()["challenges"] if c["id"] == "C06")["solved"]
    bad = board.post("/api/flag", json={"flag": "DVAP{C06_0000000000000000}"}).json()
    assert bad["ok"] is False
