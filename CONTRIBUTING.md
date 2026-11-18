# Contributing to DVAP

Thanks for helping. DVAP is a teaching lab, so clarity beats cleverness: small, readable code that
a student can follow is the goal.

## Ground rules

These are not negotiable (from [CLAUDE.md](CLAUDE.md)):

- **Everything is simulated.** Never add code that connects to a real PLC, a real industrial
  protocol on an external network, Shodan/Censys, or any host outside the lab's Docker network.
- **Loopback only.** Only the `gateway` publishes ports (for the HMI, ticket form and scoreboard),
  and only on `127.0.0.1`; every other service stays on the internal network. `tests/test_lab_safety.py` enforces this.
- **Every deliberate vulnerability is documented.** Mark it in code with `# DVAP-VULN: <challenge-id>`
  and list it in [docs/VULNERABILITIES.md](docs/VULNERABILITIES.md). An undocumented weakness is a bug.
- **No real secrets.** Use `.env.example`.

## Development setup

You need Python 3.12, [uv](https://docs.astral.sh/uv/) and Docker (Compose v2).

```bash
uv sync               # install everything, including dev tools
make test             # pytest; uses a scripted fake LLM, no model or network needed
uv run ruff check .
uv run mypy
make up               # the full lab in Docker
```

The test suite starts a real virtual PLC (Modbus + OPC UA) on localhost, so it takes a few minutes.

## Adding a challenge

1. `challenges/<id>/challenge.yaml` — story, objective, setup, `success_condition`, three hints, and
   a mitigation. [docs/CHALLENGE_AUTHORING.md](docs/CHALLENGE_AUTHORING.md) describes the schema.
2. `challenges/<id>/solution.md` — a reference solution whose commands run as written.
3. An automated solver in `tests/test_solvers.py` that drives the agent loop with a scripted
   `FakeLLM` and asserts the success condition fires.
4. A scenario in `bench/scenarios.py`, and the SafeEnvelope behaviour for it in
   `tests/test_safeenvelope.py` and `tests/test_bench.py` — including when the guard does *not*
   stop it.
5. The vulnerability in `docs/VULNERABILITIES.md` and the challenge table in `README.md`.

## Pull requests

- Keep each PR to one change, with tests. `make test`, `ruff` and `mypy` must pass (CI runs them,
  plus `docker compose build`).
- Update `docs/` when behaviour changes.
- Security-relevant changes to `docker-compose.yml` must keep `tests/test_lab_safety.py` green; if
  you change containment on purpose, update [docs/LAB_SAFETY.md](docs/LAB_SAFETY.md) in the same PR.
- By contributing you agree that your contribution is licensed under the [Apache License 2.0](LICENSE).

Found a way out of the lab? Don't open an issue — see [SECURITY.md](SECURITY.md).
