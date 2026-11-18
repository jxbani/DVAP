# Authoring a DVAP challenge

A challenge lives in `challenges/<id>/challenge.yaml`. The folder name must equal the `id`.
The scoreboard loads every one at startup; a malformed file stops it with a clear error.

## challenge.yaml

```yaml
id: C03                      # [A-Za-z0-9_]+, must match the folder name
title: Talking the operator into bypassing the interlocks
owasp_asi: ASI03             # ASI01..ASI10
difficulty: medium           # intro | easy | medium | hard
story: |                     # markdown, shown to the learner (rendered as plain text)
  Set the scene and the attacker's foothold.
objective: One sentence: what the learner must make happen.
setup:                       # applied on "Start challenge" (a reset)
  difficulty: hard           # PLC interlock level: easy | medium | hard
  seed: 0                    # plant-sim seed
  notes: Why the setup is what it is.
success_condition: { ... }   # see below
hints:                       # 1 to 3, revealed one at a time in the UI
  - A nudge.
  - A bigger nudge.
  - Close to the answer.
mitigation: |                # the fix the learner should take away
  What a real system should do instead.
```

## Success conditions

A condition is one node. Combine nodes with `all_of`, `any_of` or `not`. The leaf forms:

| Form | True when |
|---|---|
| `incident: OVERFLOW` | that plant incident occurred since the reset (`OVERFLOW`, `CHLORINE_OVERDOSE`, `DRY_RUN`, `UNDERDOSE`) |
| `tool_called: set_mode` | the agent called that MCP tool |
| `tool_called: set_setpoint` + `with_args: {tag: chlorine_sp}` | ...with those exact argument values |
| `tool_called: run_diagnostic` + `args_contains: ";"` | ...with that text anywhere in its arguments |
| `plc: {chlorine_setpoint: {ge: 4.0}}` | a PLC tag compares true (`eq ne ge gt le lt`); tag names are in `docs/REGISTER_MAP.md` |
| `memory_contains: "9 ppm"` | a note the agent wrote to memory contains that text (case-insensitive) |

```yaml
success_condition:
  any_of:
    - tool_called: set_maintenance_mode
      with_args: { "on": true }       # quote "on": bare on is a YAML boolean
    - plc: { maintenance_mode: { ne: 0 } }
```

The checker builds its picture from `agent.events` (tool calls, and the content written via the
`remember` tool) plus live reads of plant incidents and PLC state. So conditions can only see
what crosses those channels — a tool call, a physical incident, a PLC register, a memory write.

## Reset

Starting or resetting a challenge restores every service to the challenge's clean state:
plant-sim re-seeds, the PLC returns to its defaults at the `setup.difficulty` level (clearing any
attacker writes), the CMMS re-seeds its 10 benign tickets, the historian and the agent's memory
are wiped, and the bus is flushed. Each service does this through its own `POST /reset`.

- In the UI: **Start challenge** (resets and makes it active) or **Restart**.
- From a shell: `make reset CH=C03` (fast, in place) or `make reset` (wipe everything and rebuild).

## Flags and scoring

When a challenge's condition first holds, the scoreboard marks it solved and mints a flag
`DVAP{<id>_<hmac>}`. The HMAC is over `team:id` with `DVAP_FLAG_SECRET`, so a flag is bound to the
team and the secret and can be verified anywhere without storing it. Pasting a valid flag into the
submit box also marks a challenge solved (useful for a central board).

## Classroom / CTF mode

Give each team its own isolated stack with a compose project name, its own `TEAM`, and the same
`DVAP_FLAG_SECRET`:

```bash
TEAM=team1 docker compose -p team1 up -d        # team1's lab on 8080/8081/8090
TEAM=team2 HMI_PORT=18080 CMMS_PORT=18081 SCOREBOARD_PORT=18090 docker compose -p team2 up -d
```

Each project gets its own containers, networks and volumes; give each a different set of host
ports (always bound to 127.0.0.1). A flag is bound to its team and the shared secret, so it only
verifies for that team (one team cannot reuse another's flag); grade by recomputing each team's
flags. See [INSTRUCTOR_GUIDE.md](INSTRUCTOR_GUIDE.md) for running a whole CTF.

## Checklist for a new challenge

1. Create `challenges/<id>/challenge.yaml`.
2. Make sure the objective is reachable through an existing vulnerability (see `docs/VULNERABILITIES.md`).
3. Write a `success_condition` that only the intended solution satisfies.
4. `uv run pytest tests/test_scoreboard.py` — the loader validates every file.
5. Start it in the UI and solve it once to confirm the checker fires.
