"""The live plant: holds the true state, steps the shared model, adds sensor noise."""

import random

from dvap_common import DEFAULT_CONSTANTS, Actuators, Constants, PlantState, apply_actuators, step


class Plant:
    def __init__(self, consts: Constants = DEFAULT_CONSTANTS, seed: int = 0, noise: bool = False):
        self.consts = consts
        self.noise = noise
        self.rng = random.Random(seed)
        self.state = consts.initial.model_copy(deep=True)  # ground truth
        self.measured = self.state  # what the sensors report

    def set_actuators(self, changes: Actuators | dict) -> None:
        self.state = apply_actuators(self.state, changes)

    def step(self) -> None:
        """Advance one tick. Noise is drawn once per tick, so runs are reproducible per seed."""
        self.state = step(self.state, self.consts)
        self.measured = self._measure()

    def _measure(self) -> PlantState:
        if not self.noise:
            return self.state
        s, c, gauss = self.state, self.consts, self.rng.gauss
        return s.model_copy(
            update={
                "tank_level_pct": min(max(s.tank_level_pct + gauss(0, c.noise_level_pct), 0.0), 100.0),
                "chlorine_ppm": max(s.chlorine_ppm + gauss(0, c.noise_ppm), 0.0),
                "inflow_rate_lps": max(s.inflow_rate_lps + gauss(0, c.noise_flow_lps), 0.0),
                "outflow_lps": max(s.outflow_lps + gauss(0, c.noise_flow_lps), 0.0),
            }
        )
