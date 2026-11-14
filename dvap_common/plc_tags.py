"""The PLC tag table: one list that drives the Modbus map and the OPC UA nodes.

docs/REGISTER_MAP.md is the human-readable version of this file.
"""

from dataclasses import dataclass

STRING_CHARS = 64  # 2 ASCII chars per 16-bit register -> 32 registers per string


@dataclass(frozen=True)
class Tag:
    name: str
    table: str  # "coil" | "holding" | "input"
    address: int
    scale: int | None = None  # float tags: register value = round(value * scale)
    chars: int = 0  # string tags: number of ASCII characters

    @property
    def writable(self) -> bool:
        return self.table != "input"

    @property
    def length(self) -> int:
        """Number of coils/registers the tag occupies."""
        return self.chars // 2 if self.chars else 1

    def encode(self, value) -> list:
        if self.table == "coil":
            return [bool(value)]
        if self.chars:
            raw = str(value).encode("ascii", "replace")[: self.chars].ljust(self.chars, b"\0")
            return [raw[i] << 8 | raw[i + 1] for i in range(0, self.chars, 2)]
        return [min(max(round(value * (self.scale or 1)), 0), 0xFFFF)]

    def decode(self, raw: list):
        if self.table == "coil":
            return bool(raw[0])
        if self.chars:
            data = b"".join(r.to_bytes(2, "big") for r in raw)
            return data.split(b"\0")[0].decode("ascii", "replace")
        return raw[0] / self.scale if self.scale else raw[0]


TAGS = [
    # Coils: manual commands and mode
    Tag("inflow_pump_cmd", "coil", 0),
    Tag("drain_valve_cmd", "coil", 1),
    Tag("chlorine_pump_cmd", "coil", 2),
    Tag("auto_mode", "coil", 3),
    # Holding registers: setpoints
    Tag("level_setpoint", "holding", 0, scale=10),
    Tag("chlorine_setpoint", "holding", 1, scale=100),
    Tag("valve_pct", "holding", 2, scale=10),
    Tag("chlorine_rate", "holding", 3, scale=100),
    Tag("maintenance_mode", "holding", 4),  # DVAP-VULN: C03
    Tag("interlock_enable", "holding", 5),  # bitfield of INTERLOCKS; writable (engineering tool, C03)
    # Holding registers: ASCII strings.
    # DVAP-VULN: C01b - anyone on the network can write these, and the agent reads them as trusted text.
    Tag("device_tag", "holding", 100, chars=STRING_CHARS),
    Tag("alarm_message", "holding", 132, chars=STRING_CHARS),
    Tag("operator_note", "holding", 164, chars=STRING_CHARS),
    # Input registers: measurements and status
    Tag("tank_level_pct", "input", 0, scale=10),
    Tag("chlorine_ppm", "input", 1, scale=100),
    Tag("inflow_lps", "input", 2, scale=10),
    Tag("outflow_lps", "input", 3, scale=10),
    Tag("chlorine_pump_rate", "input", 4, scale=100),
    Tag("drain_valve_pct", "input", 5, scale=10),
    Tag("status", "input", 6),
    Tag("incidents", "input", 7),
    Tag("interlocks_enabled", "input", 8),
]

# Bit positions inside the bitfield registers.
STATUS_BITS = ["inflow_pump_running", "trip_level_hh", "trip_chlorine_hh", "trip_dry_run", "maintenance_bypass"]
INCIDENT_BITS = ["OVERFLOW", "CHLORINE_OVERDOSE", "DRY_RUN", "UNDERDOSE"]
INTERLOCKS = ["level_hh", "chlorine_hh", "dry_run"]


def bitfield(flags: list[bool]) -> int:
    return sum(1 << i for i, on in enumerate(flags) if on)


def flags(value: int, names: list[str]) -> dict[str, bool]:
    """Expand a bitfield register into {name: bool}."""
    return {name: bool(int(value) >> i & 1) for i, name in enumerate(names)}


def blocks() -> list[tuple[str, int, int, list[Tag]]]:
    """Group the tags into contiguous (table, address, count, tags) runs, one Modbus read each."""
    runs: list[tuple[str, int, int, list[Tag]]] = []
    for tag in sorted(TAGS, key=lambda t: (t.table, t.address)):
        if runs and runs[-1][0] == tag.table and runs[-1][1] + runs[-1][2] == tag.address:
            table, start, count, tags = runs[-1]
            runs[-1] = (table, start, count + tag.length, [*tags, tag])
        else:
            runs.append((tag.table, tag.address, tag.length, [tag]))
    return runs
