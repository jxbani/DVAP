# DVAP — Damn Vulnerable Agentic Plant
An intentionally vulnerable, fully simulated industrial plant (water treatment) operated by an LLM agent via MCP tools. Purpose: teach and benchmark the OWASP Top 10 for Agentic Applications (ASI01–ASI10) with *physical* consequences, plus a defensive guard (SafeEnvelope). Target audience: OWASP community, universities, CTFs.

## Hard safety rules (never violate)
- Everything is SIMULATED. Never add code that connects to real PLCs, real industrial protocols on external networks, Shodan/Censys, or any host outside the docker network.
- All services bind to the internal docker network; only the HMI (8080), CMMS ticket form (8081), scoreboard and guard dashboard are exposed, and only on 127.0.0.1.
- Vulnerabilities are deliberate, documented, and confined to the lab. Each one must be listed in docs/VULNERABILITIES.md with its challenge ID.
- No real secrets in the repo. Use .env.example.

## Architecture (docker compose services)
- plant-sim: physics simulation of a water treatment process (tank level, inflow pump, drain valve, chlorine dosing pump, chlorine concentration, flow sensors). Ticks at 10 Hz. Deterministic given a seed.
- plc: virtual PLC exposing the plant over Modbus/TCP (pymodbus) and OPC UA (asyncua). Runs simple control logic + safety interlocks that can be toggled per difficulty level.
- hmi: FastAPI + vanilla JS/Chart.js dashboard showing live process values, alarms, and a "physical incident" banner (overflow, chlorine overdose, dry-run pump).
- cmms: mock maintenance ticket system (FastAPI + SQLite). Untrusted text source.
- historian: time-series log of process values (SQLite) with a query API.
- agent-operator: the victim LLM agent. Talks to the plant only through MCP tools served by mcp-plant.
- mcp-plant: MCP server (official `mcp` Python SDK, FastMCP) exposing operator tools.
- bus: Valkey (BSD-licensed, Redis-compatible), used for inter-agent messaging (deliberately unauthenticated in some challenges).
- scoreboard: challenge engine, reset logic, flags, scoring UI.
- safeenvelope: deterministic policy guard between the MCP tools and the PLC, enforced inline in
  mcp-plant (see docs/SAFEENVELOPE.md). Off by default; a challenge's defended variant turns it on.

## Tech conventions
- Python 3.12, uv, FastAPI, pydantic v2, pymodbus 3.x, asyncua, mcp SDK, redis-py, pytest + pytest-asyncio, ruff, mypy (non-strict).
- LLM access via LiteLLM so the agent works with Ollama (default, offline), Anthropic, or any OpenAI-compatible endpoint, selected by env vars.
- Every service has a /health endpoint and unit tests. `make up`, `make down`, `make test`, `make reset` must always work.
- Small, readable code: this is a teaching lab. Prefer clarity over cleverness; comment the deliberate vulnerabilities with `# DVAP-VULN: <challenge-id>`.

## Workflow
- Work in small steps, run tests after every change, and keep `make test` green.
- Update docs/ as features land.
