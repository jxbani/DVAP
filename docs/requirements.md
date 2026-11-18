# Requirements

DVAP runs in Docker on Linux, macOS (Intel and Apple Silicon) and Windows (WSL2 or PowerShell).
The images are published for **linux/amd64** and **linux/arm64**.

## Software

| | Version | Why |
|---|---|---|
| Docker Engine (or Docker Desktop) | 24.0 or newer | runs the lab |
| Docker Compose | v2.20 or newer (`docker compose`) | `up --wait`, profiles |
| Python | 3.9 or newer | runs the `./dvap` script (standard library only); macOS, Linux distros and WSL already have it |
| git | any | only to clone; the release zip doesn't need it |
| [uv](https://docs.astral.sh/uv/) | any | only for `./dvap bench`, `make test` and contributing |

`./dvap doctor` checks all of this.

## Hardware, per LLM mode

The agent's "brain" is the main cost. Pick a mode with `./dvap up --mode <mode>`; the first run asks.

| Mode | The agent is… | Memory for Docker | Free disk | CPU | Network |
|---|---|---|---|---|---|
| `replay` | recorded responses: falls for the textbook attacks, nothing cleverer | **4 GB** | 6 GB | any 2 cores | only to pull the images |
| `ollama` | a local 7B model (`qwen2.5:7b-instruct`), fully offline once downloaded | **8 GB** | 12 GB | 4+ cores; a GPU helps on Linux | a one-time ~4.7 GB download |
| `api` | a hosted model (Anthropic, OpenAI, or any OpenAI-compatible endpoint) | **4 GB** | 6 GB | any 2 cores | the agent calls the provider; needs an API key |

- **"Memory for Docker"** is what Docker itself may use. On macOS and Windows that's the Docker
  Desktop / WSL2 limit, not the machine's RAM; doctor reads the real figure and says how to raise it.
- **`replay`** is the right choice for getting started, for classrooms of modest laptops, and for
  CI. Use **`ollama`** or **`api`** to see how a real model behaves, and [`dvap bench`](BENCHMARK.md)
  to measure it.
- **`ollama` speed:** on a CPU, expect tens of seconds per agent decision; Docker on macOS can't use
  the GPU. A smaller model is faster: set `OLLAMA_MODEL` and `MODEL` in `.env` (check its licence).
- **`api` and lab containment:** the lab has no internet access on purpose, so `api` mode gives the
  agent container (only) a route out. Use it only on a machine you control; see
  [Lab safety](LAB_SAFETY.md).
