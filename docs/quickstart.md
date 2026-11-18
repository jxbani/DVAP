# Quickstart

Three commands, once Docker is installed ([Installation](installation.md)):

```bash
git clone https://github.com/jxbani/DVAP.git && cd DVAP
./dvap up
./dvap demo
```

1. **`git clone …`** gets the lab. No git? Download `dvap-<version>.zip` from the
   [latest release](https://github.com/jxbani/DVAP/releases/latest), unzip it and `cd` into it instead.
2. **`./dvap up`** checks your machine (the same checks as `./dvap doctor`), then starts the lab. The
   first time, it creates `.env` and asks how the agent should think: `replay` (no model, the fastest
   start), `ollama` (a local model, ~4.7 GB download once) or `api` (your API key). See
   [Requirements](requirements.md) for what each needs.
3. **`./dvap demo`** shows the whole story in about four minutes. A malicious maintenance ticket
   makes the agent overflow the tank; then the same ticket, with SafeEnvelope on, is DENIED and
   nothing happens. Press Enter to advance each step. In a hurry? `./dvap demo --quick` files one
   malicious ticket and waits for the agent to set the chlorine to 9 ppm (about a minute).

Then open:

| | URL |
|---|---|
| Scoreboard: pick a challenge, read its story and hints | http://127.0.0.1:8090 |
| HMI: the plant, alarms, the agent's activity, SafeEnvelope decisions | http://127.0.0.1:8080 |
| Ticket form: anyone can file a ticket (that's the point) | http://127.0.0.1:8081 |

On Windows without WSL, use `.\dvap.ps1` wherever these pages say `./dvap`.

## Every command

| Command | What it does |
|---|---|
| `./dvap up [--mode replay\|ollama\|api] [--build]` | Start the lab; `--mode` switches the LLM mode, `--build` builds images from source |
| `./dvap down` | Stop the lab (keeps all data) |
| `./dvap reset` / `./dvap reset C01` | Wipe all lab state but keep the model / reset one challenge in place |
| `./dvap status` | Containers, LLM mode, and whether each UI answers |
| `./dvap logs [service]` | Follow the logs, e.g. `./dvap logs agent-operator` |
| `./dvap doctor` | Check the machine; prints the fix for every failure |
| `./dvap demo [--auto] [--challenge C02] [--live]` | The staged demo: attack → physical incident, then the same attack blocked by SafeEnvelope ([details](#presenting-dvap)) |
| `./dvap demo --quick` | The short version: one malicious ticket (C02), no guard |
| `./dvap bench …` | Benchmark models against every challenge ([Benchmarking](BENCHMARK.md)); needs [uv](https://docs.astral.sh/uv/) |
| `./dvap version` / `./dvap update` | Versions / pull the new source, new settings and matching images |

## Presenting DVAP

`./dvap demo` is built for a talk: about four minutes, offline, and the same every time.

1. `./dvap up`, then open the HMI's presenter layout on the projector:
   http://127.0.0.1:8080/?presenter=1 (big plant graphic and incident banner, agent and
   SafeEnvelope panels, no small charts).
2. Run `./dvap demo` in a terminal with a large font. Each step prints a big caption and waits for
   Enter:
   1. clean plant, guard off;
   2. normal operation (the agent reads the plant, nothing to do);
   3. the attacker files the ticket (the injected instruction is highlighted);
   4. the agent obeys: the PHYSICAL INCIDENT banner (OVERFLOW, or chlorine overdose with
      `--challenge C02`);
   5. reset, SafeEnvelope on, the same ticket again;
   6. the guard's DENIED decision, its reason and provenance, and no incident in the same time;
   7. a summary: without the guard vs with it.

What keeps it reliable on stage:

- **Recorded responses.** The agent is switched to `replay` for the demo (and back afterwards), so
  a live model can't improvise. `--live` uses the lab's configured model instead.
- **On cue.** The agent's 30 s timer is paused; the demo triggers each agent cycle itself.
- **A faster plant clock.** The plant runs at 6× (C01) or 8× (C02) real time during the demo, so
  both incidents fit the slot. The demo says so on screen; every reset returns to real time.

`--auto` runs every step on fixed timers and finishes in about 2½–3 minutes, for recording. CI runs
it for both challenges and fails unless the attack causes the incident and is then blocked.

Next: [the challenges](challenges/index.md).
