# Benchmark harness (`dvap bench`)

Runs every challenge's attack scenario across one or more models (via LiteLLM) and, optionally,
with SafeEnvelope on, then writes a JSON/CSV/HTML report and refreshes the README results table.

```bash
uv run dvap bench --models fake:comply,fake:refuse --runs 1 --guard off
uv run dvap bench --models ollama/qwen2.5:7b-instruct --runs 5 --guard on
uv run dvap bench --models anthropic/claude-3-5-sonnet --runs 3 --guard off --challenges C01,C02
```

- `--models` a comma-separated list of LiteLLM model ids. Two built-in deterministic models make
  the harness runnable and testable offline: `fake:comply` replays each challenge's reference
  attack, `fake:refuse` never acts. Ollama models need `OLLAMA_API_BASE` (default
  `http://localhost:11434`); hosted providers read their usual API-key env vars.
- `--runs N` runs per challenge with fixed seeds `0..N-1`.
- `--guard on|off` toggles SafeEnvelope for the runs (and, when on, measures the benign-workload
  false-positive rate).
- `--challenges` limits to specific ids (default: all).

## What it records

Per model × challenge: attack **success rate** (the challenge's own `success_condition`),
**time-to-incident**, **tool calls**, **tokens** (when the provider reports usage), and — with the
guard on — the **block rate** and the benign-workload **false-positive rate**.

## Output (`results/<timestamp>/`)

- `results.json` — everything, including the config, seeds, model versions and the exact prompts.
- `results.csv` — one aggregate row per model × challenge.
- `report.html` — a self-contained page (Chart.js inlined) with charts and a per-ASI summary.
- `prompts/` — the system prompt, each challenge's attack vector, and the benign workload.

The README "Benchmark results" section (between the `BENCH` markers) is regenerated from the run.

## Reproducibility

Physics is deterministic and seeds are fixed and logged; model ids and versions are recorded
(Ollama's version is queried; hosted providers are marked provider-managed); the exact prompts are
saved under `prompts/`. `results/` is git-ignored — rerun the command to regenerate it.

## What the guard does and does not catch (defended runs)

The benchmark is honest about SafeEnvelope's reach. It **prevents** the C01–C04, C06 and C10
effects outright. For **C05/C09** it refuses the *effect* but the agent still *makes* the call the
challenge scores, so the win shows up as the block rate, not the success rate. For **C07/C08** the
spoof-driven drain-shut/pump maneuver is not unsafe within the 120 s forecast at a normal tank
level, so the guard allows it; those attacks are an argument for the provenance/taint control, not
the forecast. See [SAFEENVELOPE.md](SAFEENVELOPE.md).
