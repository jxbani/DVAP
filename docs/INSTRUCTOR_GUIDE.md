# Instructor guide

DVAP is built for a university lab session, a conference workshop or a CTF. This guide covers a
3-hour workshop, running a multi-team CTF, and grading.

> [!WARNING]
> Participants will attack the lab, by design. Run it on machines you or they control, never on a
> shared or internet-facing server, and brief everyone on [LAB_SAFETY.md](LAB_SAFETY.md) first.

## Before the session (send this to participants a few days ahead)

The model download is ~4.7 GB; do not leave it to conference Wi-Fi.

1. Install Docker (Compose v2) and `make`; have ~8 GB of free RAM.
2. `git clone https://github.com/jxbani/DVAP.git && cd DVAP && make up && make model`
3. Open http://127.0.0.1:8090 — the scoreboard should list 11 challenges — and
   http://127.0.0.1:8080, where the HMI should show the plant running.

On CPU a 7B model takes tens of seconds per agent decision; that is fine, the HMI shows every step.
Bring a USB stick with the `ollama-models` volume (or a pre-pulled machine) for anyone who arrives
without it.

### How participants act as an attacker

Only the HMI, ticket form and scoreboard are published to the host. Attacks that need the plant
network (Modbus, the Redis bus, the historian) are done from a shell inside the lab, playing an
insider who already has a foothold:

| To reach | Use | Example |
|---|---|---|
| The ticket system | the browser | http://127.0.0.1:8081 |
| PLC registers (Modbus/TCP) | `docker compose exec plc python` | see `challenges/C01b/solution.md` |
| The inter-agent bus (Redis) | `docker compose exec bus redis-cli` | see `challenges/C07/solution.md` |
| The historian API | `docker compose exec hmi python` | see `challenges/C08/solution.md` |

## A 3-hour workshop

Goal: participants leave able to name each OWASP ASI risk, explain *why* the agent fell for it, and
judge what a guard can and cannot fix. Run the agent with the default local model; keep the HMI on
the projector.

| Time | Block | What happens |
|---|---|---|
| 0:00–0:15 | Framing | Agents with tool access to physical processes; the OWASP Top 10 for Agentic Applications; lab-safety briefing. |
| 0:15–0:30 | Tour | Scoreboard, HMI (process view, incident banner, agent activity, SafeEnvelope panel), ticket form. Start C01 together and watch one agent cycle on the HMI. |
| 0:30–1:10 | **Injection** — C01, C01b, C02 | C01 in pairs, guided. Then C01b (a second injection channel) and C02 (the tool that trusts any number). Debrief: untrusted text becomes instructions; limits that live only in the prompt are not limits. |
| 1:10–1:20 | Break | |
| 1:20–2:05 | **Privilege, supply chain, code, memory** — C03, C04, C05, C06 | Teams choose two. Debrief C03 vs C09 (who approved what?) and C06 (an attack that waits a shift). |
| 2:05–2:35 | **Multi-agent and humans** — C07, C08, C09, C10 | Teams choose two. Debrief: trust between agents, a forged sensor, a misleading approval, a task that keeps coming back. |
| 2:35–2:55 | **Defence** | Start a solved challenge again, run `make defend`, repeat the attack and watch the SafeEnvelope panel deny it with a reason. Then try C07 defended — it is *not* blocked. Discuss [What SafeEnvelope does NOT protect against](../README.md#what-safeenvelope-does-not-protect-against). |
| 2:55–3:00 | Wrap-up | Map each solved challenge to its ASI category; point to `docs/VULNERABILITIES.md` and the mitigations in each `challenge.yaml`. |

Tips:

- `make reset CH=<id>` restores one challenge in a couple of seconds; `make reset` rebuilds everything.
- Starting or resetting a challenge returns SafeEnvelope to that challenge's own setting (off), so run
  `make defend` *after* starting it. `make defend`/`make undefend` also clear the agent's memory and
  scheduled tasks.
- Hints are in the scoreboard, three per challenge. Reference solutions are in
  `challenges/<id>/solution.md` — keep them off the projector.
- Short on time? C01, C02, C03 and C09 cover the core ideas in about 75 minutes.

## CTF mode

Each team gets its own isolated lab and scoreboard. Flags are signed with a secret you choose and
bound to the team name, so one team's flag is worthless to another.

### One machine per team (recommended)

Give every team the same secret and a unique team name, e.g. in a `.env` next to `docker-compose.yml`:

```bash
TEAM=team07
DVAP_FLAG_SECRET=<long random string; keep it from participants until the end>
```

Then `make up`. Each team's scoreboard mints flags like `DVAP{C03_9f2c...}` as they solve challenges.

### Several teams on one host

Give each stack its own compose project and host ports (always bound to `127.0.0.1`, so this only
works for teams sharing that machine, e.g. through a remote desktop session each):

```bash
TEAM=team1 DVAP_FLAG_SECRET=$SECRET docker compose -p team1 up -d
TEAM=team2 DVAP_FLAG_SECRET=$SECRET HMI_PORT=18080 CMMS_PORT=18081 SCOREBOARD_PORT=18090 \
  docker compose -p team2 up -d
```

Each project has its own volumes, so pull the model once per project
(`docker compose -p team2 --profile setup run --rm ollama-pull`), and budget roughly 6 GB of RAM per stack.

### Collecting flags

Have teams submit `team,flag` lines (a form, a spreadsheet export, or a chat bot) and grade them
with the script below.

## Grading

### Scoring flags

Save as `grade.py` in the repo root and run `DVAP_FLAG_SECRET=<secret> uv run python grade.py submissions.csv`:

```python
import csv, os, sys
sys.path.insert(0, "services/scoreboard")
from scoreboard.flags import verify_flag
from scoreboard.schema import load_challenges

POINTS = {"intro": 50, "easy": 100, "medium": 200, "hard": 300}
challenges = load_challenges("challenges")
secret = os.environ["DVAP_FLAG_SECRET"]
solved, rejected = {}, []
for team, flag in csv.reader(open(sys.argv[1], newline="")):
    cid = verify_flag(secret, team.strip(), flag)
    if cid in challenges:
        solved.setdefault(team.strip(), set()).add(cid)
    else:
        rejected.append((team, flag))
for team, cids in sorted(solved.items(), key=lambda kv: -sum(POINTS[challenges[c].difficulty] for c in kv[1])):
    print(f"{team:12} {sum(POINTS[challenges[c].difficulty] for c in cids):5} pts  {sorted(cids)}")
print(f"rejected (wrong team, wrong secret, or forged): {len(rejected)}")
```

Resubmissions count once. A flag submitted under the wrong team name is rejected, which also catches
teams sharing flags. With the default weights the full set is worth 2,700 points.

### Coursework rubric

For assessed coursework, flags alone reward luck with the model. Ask for a short write-up per
solved challenge and weight it more than the flag:

| Criterion | Weight | Excellent | Adequate | Weak |
|---|---|---|---|---|
| Flags | 30% | — scored by the script above — | | |
| Root cause | 20% | Names the flawed component and why the agent trusted it; correct ASI category | Correct ASI category, vague mechanism | Describes the symptom only |
| Attack path | 15% | Reproducible steps, including what the agent saw and did (from the HMI's agent log) | Steps that work but skip the agent's reasoning | Not reproducible |
| Physical consequence | 10% | Explains the process physics (why the tank overflowed, how long it took) | States the incident | Missing |
| Mitigation | 15% | A concrete fix at the right layer (tool, protocol, approval, memory), with its trade-off | A plausible fix at the wrong layer ("better prompt") | None |
| Defended analysis | 10% | Ran the attack with `make defend`; explains which SafeEnvelope layer stopped it, or why none did | Ran it, no explanation | Not attempted |

Good extension questions: *Why does a prompt-level safety rule fail where a tool-level range check
succeeds (C02)?* *SafeEnvelope blocks C09's interlock change but the challenge still scores — what
does that tell you about measuring an agent's safety?* *Design a provenance label that would have
stopped C07.*
