import pytest
from fastapi.testclient import TestClient

from dvap_common import DEFAULT_CONSTANTS as C
from dvap_common import PlantState, forecast, step
from plant_sim.api import app
from plant_sim.plant import Plant


def state(**overrides) -> PlantState:
    """A calm mid-level tank with everything off, plus overrides."""
    base = {"tank_level_pct": 50, "chlorine_ppm": 1.0}
    return PlantState(**(base | overrides))


def run(s: PlantState, seconds: float, consts=C) -> PlantState:
    return forecast(s, {}, seconds, consts)


# --- mass balance ---------------------------------------------------------


def test_water_mass_balance():
    s = state(inflow_pump_on=True, drain_valve_pct=40)
    litres_in_minus_out = 0.0
    for _ in range(600):
        s = step(s)
        litres_in_minus_out += (s.inflow_rate_lps - s.outflow_lps) / C.tick_hz
    assert (s.tank_level_pct - 50) / 100 * C.tank_volume_l == pytest.approx(litres_in_minus_out)


def test_filling_with_valve_closed():
    s = run(state(inflow_pump_on=True), 10)
    assert s.tank_level_pct == pytest.approx(50 + 100 * 10 * C.inflow_nominal_lps / C.tank_volume_l)
    assert s.outflow_lps == 0


def test_tank_never_goes_negative():
    s = run(state(tank_level_pct=1, drain_valve_pct=100), 600)
    assert 0 <= s.tank_level_pct < 0.01


def test_chlorine_mass_conserved_under_dilution():
    no_decay = C.model_copy(update={"chlorine_decay_per_s": 0.0})
    before = state(inflow_pump_on=True)
    after = run(before, 60, no_decay)
    assert after.chlorine_ppm < before.chlorine_ppm
    assert after.chlorine_ppm * after.tank_level_pct == pytest.approx(before.chlorine_ppm * before.tank_level_pct)


def test_chlorine_decays_and_dosing_raises_it():
    assert run(state(), 60).chlorine_ppm < 1.0
    assert run(state(chlorine_pump_rate=10), 60).chlorine_ppm > 1.0


# --- incidents ------------------------------------------------------------


def test_overflow():
    s = state(tank_level_pct=99, inflow_pump_on=True)
    assert run(s, 4).incidents == []
    assert run(s, 6).incidents == ["OVERFLOW"]


def test_chlorine_overdose_needs_10s_sustained():
    s = state(chlorine_ppm=5)
    assert run(s, 9.9).incidents == []
    assert run(s, 10).incidents == ["CHLORINE_OVERDOSE"]


def test_overdose_timer_resets_when_ppm_recovers():
    s = run(state(chlorine_ppm=5), 9)
    s = s.model_copy(update={"chlorine_ppm": 3.0})
    s = run(s, 1).model_copy(update={"chlorine_ppm": 5.0})
    assert run(s, 9).incidents == []


def test_dry_run():
    assert run(state(tank_level_pct=5, inflow_pump_on=True), 1).incidents == []
    s = step(state(tank_level_pct=1, inflow_pump_on=True))
    assert s.pump_dry_run and s.incidents == ["DRY_RUN"]
    assert not step(state(tank_level_pct=1)).pump_dry_run  # pump off


def test_incidents_latch():
    s = run(state(tank_level_pct=1, inflow_pump_on=True), 60)
    assert not s.pump_dry_run and s.incidents == ["DRY_RUN"]


def test_underdose_is_only_a_warning():
    s = state(chlorine_ppm=0.1)
    assert run(s, 29).warnings == []
    late = run(s, 30)
    assert late.warnings == ["UNDERDOSE"] and late.incidents == []


def test_default_plant_is_stable():
    s = run(C.initial, 600)
    assert s.incidents == [] and s.warnings == []
    assert s.tank_level_pct == pytest.approx(50, abs=1)


# --- determinism ----------------------------------------------------------


def noisy_trace(seed: int) -> list[PlantState]:
    plant = Plant(seed=seed, noise=True)
    trace = []
    for _ in range(200):
        plant.step()
        trace.append(plant.measured)
    return trace


def test_same_seed_same_trace():
    assert noisy_trace(42) == noisy_trace(42)
    assert noisy_trace(42) != noisy_trace(43)


def test_noise_does_not_touch_the_true_state():
    quiet, noisy = Plant(), Plant(seed=1, noise=True)
    for _ in range(100):
        quiet.step()
        noisy.step()
    assert noisy.state == quiet.state
    assert noisy.measured != noisy.state


# --- forecast -------------------------------------------------------------


def test_forecast_matches_simulation():
    changes = {"drain_valve_pct": 20, "chlorine_pump_rate": 8}
    plant = Plant()
    predicted = forecast(plant.state, changes, 120)
    plant.set_actuators(changes)
    for _ in range(1200):
        plant.step()
    assert predicted.tank_level_pct == pytest.approx(plant.state.tank_level_pct, abs=1e-6)
    assert predicted.chlorine_ppm == pytest.approx(plant.state.chlorine_ppm, abs=1e-6)
    assert predicted.incidents == plant.state.incidents


def test_forecast_is_pure_and_validates():
    s = state()
    forecast(s, {"inflow_pump_on": True}, 5)
    assert s == state()
    with pytest.raises(ValueError):
        forecast(s, {"drain_valve_pct": 150}, 1)


# --- API ------------------------------------------------------------------

client = TestClient(app)  # not used as a context manager, so the tick loop does not run


def test_api():
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/state").json()["tank_level_pct"] == 50
    r = client.post("/actuators", json={"drain_valve_pct": 10})
    assert r.status_code == 200 and r.json()["drain_valve_pct"] == 10
    assert r.json()["inflow_pump_on"] is True  # untouched fields keep their value


def test_api_rejects_bad_actuators():
    assert client.post("/actuators", json={"chlorine_pump_rate": 11}).status_code == 422
    assert client.post("/actuators", json={"tank_level_pct": 0}).status_code == 422
