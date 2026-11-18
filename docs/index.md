# DVAP — Damn Vulnerable Agentic Plant

DVAP is a deliberately vulnerable, fully simulated water-treatment plant run by an LLM agent through
MCP tools. Every challenge maps to the [OWASP Top 10 for Agentic Applications](https://genai.owasp.org/)
(ASI01–ASI10), and every successful attack has a *physical* consequence on the HMI: the tank
overflows, the chlorine overdoses, the pump runs dry.

!!! warning
    DVAP is intentionally insecure. Run it only on a machine you control, keep every port on
    `127.0.0.1`, and never connect it to real equipment. Read [Lab safety](LAB_SAFETY.md) first.

## Quickstart

You need Docker (with Compose v2). Either download `dvap-<version>.zip` from the
[latest release](https://github.com/jxbani/DVAP/releases/latest) and unzip it, or clone the repo:

```bash
git clone https://github.com/jxbani/DVAP.git && cd DVAP
./dvap doctor    # PASS/FAIL checks, with the fix for anything that fails
./dvap up        # first run: creates .env and asks which LLM mode to use
./dvap demo      # a malicious ticket makes the agent overdose the chlorine
```

Then open the scoreboard at http://127.0.0.1:8090 and the HMI at http://127.0.0.1:8080. The
[README](https://github.com/jxbani/DVAP#readme) covers the LLM modes and their hardware needs,
every command, platform notes and troubleshooting.

## Where to next

- Teaching a class or running a CTF: [Instructor guide](INSTRUCTOR_GUIDE.md)
- What each challenge exploits: [Vulnerabilities](VULNERABILITIES.md)
- The defensive guard to attack: [SafeEnvelope](SAFEENVELOPE.md)
- Measuring how often a model falls for each attack: [Benchmarking](BENCHMARK.md)
- Writing a new challenge: [Authoring a challenge](CHALLENGE_AUTHORING.md)
