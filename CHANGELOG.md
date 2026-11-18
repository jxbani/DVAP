# Changelog

All notable changes to DVAP are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and DVAP uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html). For challenges, a breaking change is
one that changes a published challenge's success condition or its reference solution.

The release workflow publishes the section for a version as that release's notes, so write
entries for the people running the lab. How to cut a release: [docs/RELEASING.md](docs/RELEASING.md).

## [Unreleased]

## [1.0.0] - 2026-11-19

The first release. (A 0.9.0-beta.1 pre-release was prepared but never published, so its changes
are all here; the external beta it was for has not run yet.)

### Added

- A simulated water-treatment plant (plant-sim, 10 Hz, deterministic per seed) behind a virtual
  PLC speaking Modbus/TCP and OPC UA, with an HMI, historian, CMMS ticket system, Valkey message
  bus, maintenance-planner agent and a third-party vendor MCP server.
- The operator agent (LiteLLM: Ollama, Anthropic or any OpenAI-compatible endpoint) and its MCP
  server, mcp-plant.
- Eleven challenges, C01–C10 plus C01b, mapped to the OWASP Top 10 for Agentic Applications, each
  with a story, three hints, a mitigation, a reference solution and an automated solver.
- A scoreboard with per-challenge resets and team-bound HMAC flags for CTFs.
- SafeEnvelope, a deterministic policy guard between the MCP tools and the PLC, with defended
  variants of the challenges (`./dvap defend` turns it on for the running challenge).
- The `./dvap` CLI (`dvap.ps1` on Windows): `up`, `down`, `reset`, `status`, `logs`, `doctor`,
  `defend`, `demo`, `bench`, `version`, `update`, with a first-run wizard.
- Three LLM modes: `replay` (recorded responses, no model), `ollama` (local model) and `api`
  (hosted model).
- `./dvap demo`: a staged, four-minute talk demo (attack → physical incident, then the same attack
  DENIED by SafeEnvelope), with `--auto` for recording, `--challenge C01|C02` and `--live`;
  `./dvap demo --quick` is the one-attack version. The HMI has a presenter layout
  (`?presenter=1`).
- `dvap bench`: benchmarks models (and the guard) against every challenge, with JSON, CSV and HTML
  reports.
- Prebuilt multi-arch images (linux/amd64, linux/arm64) on GHCR, signed with cosign, with SBOMs
  and build-provenance attestations, and a `dvap-<version>.zip` that runs the lab without cloning.
- Documentation site (https://jxbani.github.io/DVAP/): quickstart, requirements per LLM mode,
  installation per OS, troubleshooting with the `dvap doctor` output for each problem, a spoiler-free
  page per challenge with separate solution pages, architecture, SafeEnvelope design, instructor
  guide, a presenter's guide, contributing and security policy.
- A demo GIF, a full demo video and a social preview, recorded from a live run by
  `scripts/record_demo.py` (optional `media` dependency group).
- For maintainers: a fresh-install check (`scripts/verify_fresh_install.sh` and the Fresh install
  workflow: the release zip and published images on Ubuntu, a WSL-like container and Intel macOS,
  from download to C01's overflow in under 15 minutes); SemVer pre-release tags
  (`vX.Y.Z-beta.N`), published as GitHub pre-releases; and a beta kit (docs/BETA_TESTING.md, a
  beta feedback issue form and `scripts/beta_report.py`).

### Security

- Every port is published by one hardened gateway, on 127.0.0.1 only; the vulnerable services,
  the UIs included, have no route out of the lab.
- The diagnostic sandbox runs as `nobody`, read-only, with all capabilities dropped.
- LiteLLM runs in offline mode, so it never fetches catalogs from the internet.
- The scoreboard refuses to mint flags for a CTF team that uses a public flag secret.
- Every image and GitHub Action is pinned by digest or commit SHA, and Python dependencies by
  `uv.lock`; CI fails on any fixable CRITICAL vulnerability in DVAP's images.

[Unreleased]: https://github.com/jxbani/DVAP/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/jxbani/DVAP/releases/tag/v1.0.0
