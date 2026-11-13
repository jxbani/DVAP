"""PLC control logic: AUTO/MANUAL control plus safety interlocks. Pure, no I/O."""

from plc.tags import INTERLOCKS


def clamp(x: float, lo: float, hi: float) -> float:
    return min(max(x, lo), hi)


class PI:
    """PI controller with a clamped output and integral (anti-windup)."""

    def __init__(self, kp: float, ki: float, lo: float, hi: float, start: float = 0.0):
        self.kp, self.ki, self.lo, self.hi = kp, ki, lo, hi
        self.integral = start

    def update(self, error: float, dt: float) -> float:
        self.integral = clamp(self.integral + self.ki * error * dt, self.lo, self.hi)
        return clamp(self.kp * error + self.integral, self.lo, self.hi)


class Controller:
    def __init__(self, cfg: dict, enabled: dict[str, bool]):
        self.cfg = cfg
        self.enabled = enabled  # interlock name -> enabled at this difficulty
        self.tripped = dict.fromkeys(INTERLOCKS, False)  # condition present (with hysteresis)
        d, c = cfg["defaults"], cfg["control"]
        self.level_pi = PI(c["level"]["kp"], c["level"]["ki"], 0, 100, start=d["valve_pct"])
        self.chlorine_pi = PI(c["chlorine"]["kp"], c["chlorine"]["ki"], 0, 10, start=d["chlorine_rate"])

    def scan(self, mem: dict, level: float, ppm: float, dt: float) -> tuple[dict, dict[str, bool]]:
        """One PLC scan. Returns (actuator outputs, interlocks currently acting)."""
        if mem["auto_mode"]:
            # AUTO: pump runs, the drain valve holds the level, the dosing pump holds the chlorine.
            pump = True
            valve = self.level_pi.update(level - mem["level_setpoint"], dt)
            dose = self.chlorine_pi.update(mem["chlorine_setpoint"] - ppm, dt)
        else:
            # MANUAL: operator commands pass straight through.
            pump = bool(mem["inflow_pump_cmd"])
            valve = clamp(mem["valve_pct"], 0, 100) if mem["drain_valve_cmd"] else 0.0
            dose = clamp(mem["chlorine_rate"], 0, 10) if mem["chlorine_pump_cmd"] else 0.0
            # Keep the PI loops tracking so switching back to AUTO does not bump the outputs.
            self.level_pi.integral, self.chlorine_pi.integral = valve, dose

        limits = self.cfg["interlocks"]
        self._update_trip("level_hh", level >= limits["level_hh"]["trip"], level < limits["level_hh"]["reset"])
        self._update_trip("chlorine_hh", ppm >= limits["chlorine_hh"]["trip"], ppm < limits["chlorine_hh"]["reset"])
        self._update_trip("dry_run", level <= limits["dry_run"]["trip"], level > limits["dry_run"]["reset"])

        # DVAP-VULN: C03 - any non-zero value in the maintenance_mode register disables every
        # interlock. The register is writable by anyone on the network, with no authentication.
        bypass = mem["maintenance_mode"] != 0
        acting = {k: self.tripped[k] and self.enabled[k] and not bypass for k in INTERLOCKS}
        if acting["level_hh"]:
            pump = False
        if acting["chlorine_hh"]:
            dose = 0.0
        if acting["dry_run"]:
            valve = 0.0

        return {"inflow_pump_on": pump, "drain_valve_pct": valve, "chlorine_pump_rate": dose}, acting

    def _update_trip(self, name: str, trip: bool, reset: bool) -> None:
        if trip:
            self.tripped[name] = True
        elif reset:
            self.tripped[name] = False
