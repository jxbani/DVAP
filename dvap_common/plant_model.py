"""Water-treatment plant model: state, constants and the physics step.

Shared by plant-sim (which runs it live) and forecast() (which runs it ahead of
time). Everything here is simulated and deterministic; there is no I/O besides
reading the YAML constants file.
"""

import math
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field


class PlantState(BaseModel):
    # Actuators (set by the PLC)
    inflow_pump_on: bool = False
    drain_valve_pct: float = Field(0.0, ge=0, le=100)
    chlorine_pump_rate: float = Field(0.0, ge=0, le=10)
    # Process values
    tank_level_pct: float = Field(50.0, ge=0, le=100)
    chlorine_ppm: float = 0.0
    inflow_rate_lps: float = 0.0
    outflow_lps: float = 0.0
    pump_dry_run: bool = False
    # Incidents latch until the plant is reset; warnings reflect the current tick.
    incidents: list[str] = []
    warnings: list[str] = []
    # Bookkeeping
    t: float = 0.0  # simulated seconds
    overdose_s: float = 0.0  # how long ppm has been above the overdose limit
    underdose_s: float = 0.0  # how long ppm has been below the underdose limit


class Actuators(BaseModel):
    """A partial actuator update. Omitted fields keep their current value."""

    model_config = ConfigDict(extra="forbid")

    inflow_pump_on: bool | None = None
    drain_valve_pct: float | None = Field(None, ge=0, le=100)
    chlorine_pump_rate: float | None = Field(None, ge=0, le=10)


class Constants(BaseModel):
    tick_hz: float
    tank_volume_l: float
    inflow_nominal_lps: float
    drain_max_lps: float
    dose_mg_per_s_per_unit: float
    chlorine_decay_per_s: float
    min_mix_volume_l: float
    overdose_ppm: float
    overdose_sustain_s: float
    underdose_ppm: float
    underdose_sustain_s: float
    dry_run_level_pct: float
    noise_level_pct: float
    noise_ppm: float
    noise_flow_lps: float
    initial: PlantState


def load_constants(path: str | Path) -> Constants:
    return Constants.model_validate(yaml.safe_load(Path(path).read_text()))


DEFAULT_CONSTANTS = load_constants(
    os.environ.get("DVAP_PLANT_CONFIG", Path(__file__).with_name("plant.yaml"))
)


def _advance(s: PlantState, c: Constants, dt: float) -> None:
    """Advance `s` in place by one tick of `dt` seconds."""
    volume = s.tank_level_pct / 100 * c.tank_volume_l

    # Hydraulics: constant-rate pump in, gravity drain out (Torricelli: flow ~ sqrt(level)).
    s.pump_dry_run = s.inflow_pump_on and s.tank_level_pct < c.dry_run_level_pct
    s.inflow_rate_lps = c.inflow_nominal_lps if s.inflow_pump_on else 0.0
    drain = c.drain_max_lps * s.drain_valve_pct / 100 * math.sqrt(s.tank_level_pct / 100)
    s.outflow_lps = min(drain, volume / dt + s.inflow_rate_lps)  # cannot drain water that is not there
    new_volume = volume + (s.inflow_rate_lps - s.outflow_lps) * dt

    # Chlorine: well-mixed tank. Mass in from dosing, out with the outflow and by decay.
    # Clean inflow dilutes it because the same mass is spread over more water.
    mass = s.chlorine_ppm * max(volume, c.min_mix_volume_l)
    dose = s.chlorine_pump_rate * c.dose_mg_per_s_per_unit
    mass += (dose - s.outflow_lps * s.chlorine_ppm - c.chlorine_decay_per_s * mass) * dt
    s.chlorine_ppm = max(mass, 0.0) / max(new_volume, c.min_mix_volume_l)

    # Anything above the brim spills (taking its chlorine with it).
    overflow = new_volume >= c.tank_volume_l
    s.tank_level_pct = min(new_volume, c.tank_volume_l) / c.tank_volume_l * 100

    s.overdose_s = s.overdose_s + dt if s.chlorine_ppm > c.overdose_ppm else 0.0
    s.underdose_s = s.underdose_s + dt if s.chlorine_ppm < c.underdose_ppm else 0.0
    eps = 1e-9  # summing 0.1 a hundred times gives 9.99999..., not 10

    incidents = set(s.incidents)
    if overflow:
        incidents.add("OVERFLOW")
    if s.overdose_s >= c.overdose_sustain_s - eps:
        incidents.add("CHLORINE_OVERDOSE")
    if s.pump_dry_run:
        incidents.add("DRY_RUN")
    s.incidents = sorted(incidents)
    s.warnings = ["UNDERDOSE"] if s.underdose_s >= c.underdose_sustain_s - eps else []
    s.t += dt


def step(state: PlantState, consts: Constants = DEFAULT_CONSTANTS) -> PlantState:
    """Return the state one tick later. Does not modify `state`."""
    s = state.model_copy(deep=True)
    _advance(s, consts, 1 / consts.tick_hz)
    return s


def apply_actuators(state: PlantState, changes: Actuators | dict) -> PlantState:
    """Return a copy of `state` with validated actuator changes applied."""
    update = Actuators.model_validate(changes).model_dump(exclude_none=True)
    return state.model_copy(update=update, deep=True)


def forecast(
    state: PlantState,
    actuator_changes: Actuators | dict,
    seconds: float,
    consts: Constants = DEFAULT_CONSTANTS,
) -> PlantState:
    """Predict the state `seconds` from now if `actuator_changes` were applied now.

    Pure: uses the exact model plant-sim runs, without sensor noise.
    """
    s = apply_actuators(state, actuator_changes)
    dt = 1 / consts.tick_hz
    for _ in range(round(seconds * consts.tick_hz)):
        _advance(s, consts, dt)
    return s
