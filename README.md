# DVAP — Damn Vulnerable Agentic Plant

[![CI](https://github.com/jxbani/DVAP/actions/workflows/ci.yml/badge.svg)](https://github.com/jxbani/DVAP/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/jxbani/DVAP)](https://github.com/jxbani/DVAP/releases/latest)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/jxbani/DVAP/badge)](https://scorecard.dev/viewer/?uri=github.com/jxbani/DVAP)

**A simulated water-treatment plant run by an LLM agent, where every attack on the agent has a
physical consequence: the tank overflows, the chlorine overdoses, the pump runs dry.** Eleven
hands-on challenges, mapped to the OWASP Top 10 for Agentic Applications, plus a deterministic
guard to attack and a benchmark to measure models with.

[![DVAP demo: a malicious maintenance ticket makes the AI operator overflow the tank](docs/assets/demo.gif)](docs/assets/demo-full.mp4)

▶ [Watch the full demo](docs/assets/demo-full.mp4) (2½ min): the attack, then the same attack blocked by SafeEnvelope.

> [!WARNING]
> **DVAP is deliberately vulnerable.** Everything in it is simulated. Run it only on a machine you
> control, keep its ports on `127.0.0.1`, and **never connect it to real industrial equipment** or
> an industrial network. See [Lab safety](https://jxbani.github.io/DVAP/LAB_SAFETY/).

## Quickstart

You need Docker with Compose v2 ([requirements](https://jxbani.github.io/DVAP/requirements/)).

```bash
git clone https://github.com/jxbani/DVAP.git && cd DVAP
./dvap up        # checks your machine, then starts the lab (first run asks which LLM mode to use)
./dvap demo      # an attack overflows the tank; then SafeEnvelope blocks the same attack
```

`./dvap demo` is a staged, four-minute demo made for talks: Enter advances each step (`--auto` runs
it on timers, for recording), and it uses recorded agent responses so it can't go wrong on stage.
`./dvap demo --quick` is the one-minute version: a single attack, no guard.

Then open the scoreboard at http://127.0.0.1:8090 and the plant's HMI at http://127.0.0.1:8080.
No clone needed: each [release](https://github.com/jxbani/DVAP/releases/latest) has a
`dvap-<version>.zip`. Windows without WSL: `.\dvap.ps1 up`. Problems: `./dvap doctor`, then
[troubleshooting](https://jxbani.github.io/DVAP/troubleshooting/).

## Challenges

<!-- CHALLENGES:START -->
| ID | Challenge | OWASP ASI | Difficulty | What happens |
|---|---|---|---|---|
| [C01](https://jxbani.github.io/DVAP/challenges/C01/) | Goal hijack through a maintenance ticket | ASI01 Agent Goal Hijack | easy | Tank overflow |
| [C01b](https://jxbani.github.io/DVAP/challenges/C01b/) | Goal hijack through a PLC string register | ASI01 Agent Goal Hijack | medium | Tank overflow |
| [C02](https://jxbani.github.io/DVAP/challenges/C02/) | Unsafe setpoint, no range check | ASI02 Tool Misuse & Exploitation | easy | Chlorine overdose |
| [C03](https://jxbani.github.io/DVAP/challenges/C03/) | Privilege abuse: bypassing the interlocks to overflow the tank | ASI03 Identity & Privilege Abuse | hard | Tank overflow |
| [C04](https://jxbani.github.io/DVAP/challenges/C04/) | A poisoned third-party tool and a rug-pull | ASI04 Agentic Supply Chain Vulnerabilities | hard | Chlorine underdose |
| [C05](https://jxbani.github.io/DVAP/challenges/C05/) | Code execution through a diagnostic, straight to a coil | ASI05 Unexpected Code Execution | hard | Direct PLC write |
| [C06](https://jxbani.github.io/DVAP/challenges/C06/) | Time-delayed memory poisoning | ASI06 Memory & Context Poisoning | hard | Chlorine overdose |
| [C07](https://jxbani.github.io/DVAP/challenges/C07/) | Spoofing a work order on the inter-agent bus | ASI07 Insecure Inter-Agent Communication | medium | Pump dry-run |
| [C08](https://jxbani.github.io/DVAP/challenges/C08/) | Cascading failure from a spoofed sensor | ASI08 Cascading Failures | hard | Pump dry-run |
| [C09](https://jxbani.github.io/DVAP/challenges/C09/) | Trust exploitation: an approval that lies to the human | ASI09 Human-Agent Trust Exploitation | hard | Interlock disabled |
| [C10](https://jxbani.github.io/DVAP/challenges/C10/) | A rogue agent that reschedules itself | ASI10 Rogue Agents | hard | Unsafe setpoint keeps returning |
<!-- CHALLENGES:END -->

Each challenge also has a defended variant, with [SafeEnvelope](https://jxbani.github.io/DVAP/SAFEENVELOPE/) on.

## Documentation

**https://jxbani.github.io/DVAP/**: [installation per OS](https://jxbani.github.io/DVAP/installation/),
[challenges](https://jxbani.github.io/DVAP/challenges/), [architecture](https://jxbani.github.io/DVAP/architecture/),
[SafeEnvelope](https://jxbani.github.io/DVAP/SAFEENVELOPE/), [benchmarking models](https://jxbani.github.io/DVAP/BENCHMARK/),
[instructor guide](https://jxbani.github.io/DVAP/INSTRUCTOR_GUIDE/) (workshops and CTFs).

## Status, contributing and security

DVAP is an independent community project. It is **not** an official OWASP project and is not
endorsed by OWASP; its challenges are mapped to the OWASP Top 10 for Agentic Applications to make
them easy to teach alongside it.

[Contributing](CONTRIBUTING.md) · [Security policy](SECURITY.md) (the deliberate vulnerabilities
are out of scope; lab escapes are in scope) · [Code of conduct](CODE_OF_CONDUCT.md) ·
[Changelog](CHANGELOG.md) · [Citing DVAP](CITATION.cff) · Licensed under [Apache-2.0](LICENSE).
