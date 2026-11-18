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
3. **`./dvap demo`** plays challenge C02 for you. It files a malicious maintenance ticket through the
   ticket form, then waits for the agent to obey it and set the chlorine to 9 ppm.

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
| `./dvap demo` | Run C02 end to end against the running lab |
| `./dvap bench …` | Benchmark models against every challenge ([Benchmarking](BENCHMARK.md)); needs [uv](https://docs.astral.sh/uv/) |
| `./dvap version` / `./dvap update` | Versions / pull the new source, new settings and matching images |

Next: [the challenges](challenges/index.md).
