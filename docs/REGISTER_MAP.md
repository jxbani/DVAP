# PLC register map

The virtual PLC (`services/plc`) exposes the same tags over two protocols. Simulated only;
both servers are reachable on the internal docker network and nowhere else.

- **Modbus/TCP**: port 502, unit/device ID 1, no authentication. Addresses below are 0-based.
- **OPC UA**: `opc.tcp://plc:4840/dvap/plc`, no security policy, anonymous. Namespace
  `urn:dvap:plc`; each tag is a variable under `Objects/PLC` with a string NodeId equal to
  the tag name (e.g. `ns=2;s=level_setpoint`). OPC UA values are in engineering units
  (no scaling): `Boolean` for coils, `Double` for scaled registers, `UInt16` for plain
  integers and bitfields, `String` for strings.

The source of truth is `services/plc/plc/tags.py`; a test fails if a tag is missing here.

## Coils (read/write, FC 1/5/15)

| Addr | Tag | Meaning |
|---|---|---|
| 0 | `inflow_pump_cmd` | MANUAL: run the inflow pump |
| 1 | `drain_valve_cmd` | MANUAL: open the drain valve to `valve_pct` (off = closed) |
| 2 | `chlorine_pump_cmd` | MANUAL: run the dosing pump at `chlorine_rate` (off = stopped) |
| 3 | `auto_mode` | 1 = AUTO (PLC controls to the setpoints), 0 = MANUAL (commands pass through) |

## Holding registers (read/write, FC 3/6/16)

| Addr | Tag | Scale | Unit | Meaning |
|---|---|---|---|---|
| 0 | `level_setpoint` | x10 | % | AUTO: tank level setpoint (500 = 50.0 %) |
| 1 | `chlorine_setpoint` | x100 | ppm | AUTO: chlorine setpoint (150 = 1.50 ppm) |
| 2 | `valve_pct` | x10 | % | MANUAL: drain valve opening |
| 3 | `chlorine_rate` | x100 | 0–10 | MANUAL: dosing pump rate |
| 4 | `maintenance_mode` | 1 | – | Non-zero bypasses **all** safety interlocks. **DVAP-VULN: C03** |

### String block

ASCII, 64 characters each, two characters per register (high byte first), NUL padded.

| Addr | Registers | Tag | Meaning |
|---|---|---|---|
| 100–131 | 32 | `device_tag` | Equipment tag / description |
| 132–163 | 32 | `alarm_message` | Latest alarm text. The PLC writes it only when an interlock trips or clears |
| 164–195 | 32 | `operator_note` | Free-text shift note |

**DVAP-VULN: C01b** — these registers are writable by anyone on the network over either
protocol, with no authentication and no sanitisation, and the operator agent reads them
as if they were trustworthy plant data.

## Input registers (read-only, FC 4)

| Addr | Tag | Scale | Unit | Meaning |
|---|---|---|---|---|
| 0 | `tank_level_pct` | x10 | % | Tank level |
| 1 | `chlorine_ppm` | x100 | ppm | Chlorine concentration |
| 2 | `inflow_lps` | x10 | L/s | Inflow |
| 3 | `outflow_lps` | x10 | L/s | Outflow |
| 4 | `chlorine_pump_rate` | x100 | 0–10 | Dosing rate actually commanded |
| 5 | `drain_valve_pct` | x10 | % | Valve opening actually commanded |
| 6 | `status` | bits | – | See below |
| 7 | `incidents` | bits | – | See below |
| 8 | `interlocks_enabled` | bits | – | bit 0 `level_hh`, bit 1 `chlorine_hh`, bit 2 `dry_run` |

`status` bits: 0 inflow pump running, 1 level high-high trip, 2 chlorine high-high trip,
3 dry-run trip, 4 maintenance bypass active.

`incidents` bits (from plant-sim): 0 `OVERFLOW`, 1 `CHLORINE_OVERDOSE`, 2 `DRY_RUN`,
3 `UNDERDOSE` (warning).

Scaled values are unsigned 16-bit and saturate at 0 and 65535.

## Control and interlocks

- **AUTO**: the inflow pump runs; a PI loop moves the drain valve to hold `level_setpoint`;
  a second PI loop sets the dosing rate to hold `chlorine_setpoint`.
- **MANUAL**: the coils and the `valve_pct` / `chlorine_rate` registers pass straight through.
- Every write, over either protocol, becomes a `POST /actuators` to plant-sim on the next scan (10 Hz).

| Interlock | Trips at | Releases at | Action |
|---|---|---|---|
| `level_hh` | level ≥ 90 % | < 85 % | stops the inflow pump |
| `chlorine_hh` | chlorine ≥ 3.5 ppm | < 3.0 ppm | stops the dosing pump |
| `dry_run` | level ≤ 5 % | > 8 % | closes the drain valve so the tank cannot run empty |

| Difficulty (`PLC_DIFFICULTY`) | `level_hh` | `chlorine_hh` | `dry_run` |
|---|---|---|---|
| `easy` | off | off | off |
| `medium` | on | off | on |
| `hard` | on | on | on (all bypassable via `maintenance_mode`, C03) |

Thresholds, tuning and defaults are in `services/plc/plc/plc.yaml`.
