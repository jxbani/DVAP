# plant-sim

Physics simulation of the water treatment tank. Ticks at 10 Hz. Simulated only.

## Model (`dvap_common/plant_model.py`)

- **Level**: `d(volume)/dt = inflow - outflow`. Inflow is a fixed rate while the pump is on.
  Outflow is a gravity drain: `drain_max * valve% * sqrt(level%)`.
- **Chlorine**: well-mixed tank. Mass is added by the dosing pump, leaves with the outflow,
  and decays at a first-order rate. Clean inflow dilutes it.
- Constants live in `dvap_common/plant.yaml` (override the path with `DVAP_PLANT_CONFIG`).

## Incidents

| Flag | Condition | Kind |
|---|---|---|
| `OVERFLOW` | level reaches 100 % | incident, latched |
| `CHLORINE_OVERDOSE` | ppm > 4.0 for 10 s | incident, latched |
| `DRY_RUN` | pump on with level < 2 % | incident, latched |
| `UNDERDOSE` | ppm < 0.2 for 30 s | warning, clears itself |

Latched incidents stay in `incidents` until the service restarts (`make reset`).

## API (docker network only, port 8000)

- `GET /health`
- `GET /state` — sensor readings (with noise if `PLANT_NOISE=1`), incidents, warnings.
- `POST /actuators` — any of `inflow_pump_on`, `drain_valve_pct` (0–100), `chlorine_pump_rate` (0–10).

Env: `PLANT_SEED` (default 0) seeds the sensor noise; `PLANT_NOISE=1` enables it.

## Forecast

```python
from dvap_common import forecast
future = forecast(state, {"drain_valve_pct": 0}, seconds=120)
future.incidents  # e.g. ["OVERFLOW"]
```

Pure function, same model as the live plant, no noise. SafeEnvelope will use it to check
an actuator change before it reaches the PLC.
