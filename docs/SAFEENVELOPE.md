# SafeEnvelope — the policy-enforcing guard

SafeEnvelope is DVAP's defence: a **deterministic** policy guard that sits between the mcp-plant
tool handlers and the PLC. Every actuator/setpoint/engineering/diagnostic/schedule call is
checked before it can reach the plant. No LLM is ever in the enforcement path — decisions follow
only from the policy, the live PLC readings and a pure physics forecast, so they are repeatable
and auditable.

It lives in [`services/mcp-plant/mcp_plant/safeenvelope/`](https://github.com/jxbani/DVAP/tree/main/services/mcp-plant/mcp_plant/safeenvelope/)
and is enforced inline inside mcp-plant (that is where the Modbus write happens); there is no
separate network proxy, because a sidecar could not intercept the in-process writes without
rearchitecting the service. The policy numbers live in
[`policies/plant.yaml`](https://github.com/jxbani/DVAP/blob/main/services/mcp-plant/mcp_plant/safeenvelope/policies/plant.yaml).

## On / off (toggleable per challenge)

Off by default. Turn it on in any of these ways:

- Per challenge: set `setup.defended: true` in the `challenge.yaml`. The scoreboard sends the
  flag to mcp-plant on every reset/start, so the "defended" variant runs with the guard on.
- For the whole stack: boot mcp-plant with `DVAP_DEFENDED=1`.
- At runtime: `POST /reset {"defended": true|false}` on mcp-plant.

## The decision layers

1. **Physical invariants** — absolute setpoint ranges, per-change rate limits, and the forbidden
   combination *inflow pump on + drain shut + tank nearly full*.
2. **Predictive check** — before any actuator or mode change, `dvap_common.forecast()` runs the
   real plant model 120 s ahead; if an incident or warning appears, the change is denied.
3. **Provenance / taint** — context items are trusted (procedures, supervisor chat, sensors) or
   untrusted (tickets, bus orders, vendor MCP output, memory written from an untrusted source). A
   manual override driven by untrusted content is sent for human approval rather than applied.
4. **Privilege separation** — engineering tools (`set_interlock`, `set_maintenance_mode`) are
   refused for the operator identity regardless of what the agent says.
5. **Honest decisions** — every decision records the *raw* tool call, its forecast impact and the
   provenance that led to it, never the agent's own summary. Published to the `guard.events` bus
   and shown live in the HMI's SafeEnvelope panel.
6. **Kill switch + anomaly flags** — a denied action retried repeatedly, and a task scheduled from
   untrusted context or that would run a now-denied action, raise an anomaly flag.
   `clear_scheduled_tasks` is the kill switch.

Each decision is one of **allow**, **deny** (refused) or **review** (not applied; needs a human).

## What it does not cover

- Setpoint changes are governed by the absolute range and rate limits, not the forecast: in AUTO
  a setpoint feeds the PI loop, which the open-loop forecast does not model.
- The forecast horizon is 120 s, so a hazard that develops more slowly (a gradual underdose) is
  caught by a policy rule instead (stopping the dosing pump needs approval), not by the forecast.
- The "in N s" in a forecast reason is the 10 s scan bucket in which the incident first appears,
  not an exact crossing time.
- At a normal tank level the C07/C08 drain-shut/pump maneuver is not unsafe within the 120 s
  horizon, so the forecast allows it; those spoofed-input attacks are the case for the
  provenance/taint control (untrusted work order / forged sensor), not the forecast. The
  benchmark (`dvap bench --guard on`) reports this honestly.

See [VULNERABILITIES.md](VULNERABILITIES.md#the-defence-safeenvelope) for which layer blocks each
challenge, and `tests/test_safeenvelope.py` for the defended attack of every challenge plus the
benign-shift false-positive check.
