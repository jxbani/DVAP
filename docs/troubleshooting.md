# Troubleshooting and FAQ

Start every investigation with:

```bash
./dvap doctor
```

It checks Docker, Compose, the memory Docker can use, free disk, the CPU architecture, the three
ports, the LLM mode and (on WSL) where the repository lives. It prints PASS, WARN or FAIL for each
check, with the exact fix under anything that isn't PASS, and exits non-zero on any FAIL. `./dvap up`
runs the same checks first and stops on a failure.

Below are the 15 problems people hit most, each with the doctor output that identifies it. Only the
relevant rows are shown; the real output lists every check.

## 1. Docker isn't installed

```text
FAIL  Docker  docker not found
              fix: Install Docker Desktop: https://docs.docker.com/desktop/

1 check(s) failed.
```

On Linux the fix line points to Docker Engine and the Compose plugin instead
(https://docs.docker.com/engine/install/). See [Installation](installation.md) for your OS.

## 2. `docker` isn't found inside WSL, although Docker Desktop is installed

```text
FAIL  Docker  docker not found
              fix: Install Docker Desktop on Windows and enable Settings > Resources > WSL integration for this distro.

1 check(s) failed.
```

Docker Desktop only puts `docker` into the WSL distributions you enable. Turn on your distro under
**Settings → Resources → WSL integration**, then open a new WSL shell.

## 3. Docker Desktop isn't running

```text
FAIL  Docker  Docker is not running: Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the do
              fix: Start Docker Desktop and wait until it says it is running.

1 check(s) failed.
```

## 4. Linux: "permission denied" on the Docker socket, or the daemon is stopped

```text
FAIL  Docker  permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock
              fix: Start it: `sudo systemctl start docker`. If it is 'permission denied': `sudo usermod -aG docker $USER`, then log out and back in.

1 check(s) failed.
```

Membership of the `docker` group only applies to new login sessions, hence the log out. (Being in
that group is equivalent to root on the machine; that's Docker's design, not DVAP's.)

## 5. Docker is too old

```text
FAIL  Docker             Engine 20.10.24 (need 24.0+)
                         fix: Update Docker. Install Docker Engine + the Compose plugin: https://docs.docker.com/engine/install/
```

Distribution packages (`docker.io` on older Ubuntu and Debian) lag behind. Install from Docker's
own repository instead.

## 6. Only the old `docker-compose` (v1) is installed

```text
FAIL  Docker Compose     the `docker compose` plugin is missing
                         fix: Install/update the Compose v2 plugin: https://docs.docker.com/compose/install/
```

DVAP needs Compose v2.20 or newer, invoked as `docker compose` (a space, not a hyphen).

## 7. macOS: not enough memory for Docker in `ollama` mode

```text
FAIL  Memory for Docker  3.8 GB (need 8 GB for ollama mode)
                         fix: Docker Desktop > Settings > Resources > Memory: set at least 8 GB, then Apply & restart.
```

Doctor reads the memory of Docker's VM, not your Mac's RAM. If the Mac can't spare 8 GB, use
`./dvap up --mode replay` (4 GB) or `--mode api` (4 GB). See [Requirements](requirements.md).

## 8. Windows/WSL2: not enough memory for Docker in `ollama` mode

```text
FAIL  Memory for Docker  5.8 GB (need 8 GB for ollama mode)
                         fix: Give WSL at least 8 GB: in %UserProfile%\.wslconfig set [wsl2] memory=8GB, then run `wsl --shutdown` and restart Docker Desktop.
```

With the WSL2 backend, Docker's memory is WSL's limit. The `.wslconfig` file should read:

```ini
[wsl2]
memory=8GB
```

## 9. Not enough free disk

```text
FAIL  Free disk          3 GB free (need 6 GB for replay mode)
                         fix: Free some space, e.g. `docker system prune` removes unused images and build cache.
```

`ollama` mode needs 12 GB, because of the 4.7 GB model. `docker system prune` doesn't touch volumes,
so it keeps a downloaded model.

## 10. A port is already in use

```text
FAIL  Port 8080          in use by another program (HMI_PORT)
                         fix: Stop it (find it with `lsof -i :8080`) or set HMI_PORT=18080 in .env.
```

On Windows the fix suggests `netstat -ano | findstr :8080`. The three ports are `HMI_PORT` (8080),
`CMMS_PORT` (8081) and `SCOREBOARD_PORT` (8090); whatever you choose, they stay bound to `127.0.0.1`.
If DVAP itself holds the port, doctor says so and passes:

```text
PASS  Port 8080          in use by DVAP's gateway (the lab is up)
```

## 11. Raspberry Pi or another 32-bit ARM board

```text
FAIL  CPU architecture   armv7l; DVAP images are amd64 + arm64
                         fix: Use an x86_64 or arm64 machine: DVAP publishes no images for this architecture.
```

A Raspberry Pi 4 or 5 works with a **64-bit** OS (it then reports `aarch64`), in `replay` or `api`
mode; a 7B model on a Pi's CPU is too slow for `ollama` mode to be useful.

## 12. `api` mode without an API key

```text
FAIL  LLM mode           api: anthropic/claude-sonnet-5-5, but ANTHROPIC_API_KEY is empty
                         fix: Put your key in .env: ANTHROPIC_API_KEY=... (or rerun `./dvap up --mode api`).
```

For `openai/…` and other OpenAI-compatible models the variable is `OPENAI_API_KEY` (plus
`OPENAI_API_BASE` for a non-OpenAI endpoint). `.env` is git-ignored; never commit a key.

## 13. `ollama` mode: the model isn't downloaded yet

```text
WARN  LLM mode           ollama: qwen2.5:7b-instruct not downloaded yet
                         fix: `./dvap up` downloads it once (~4.7 GB for the default model).

No failures (1 warning(s): see above). Next: ./dvap up
```

A warning, not a failure: `./dvap up` downloads it before starting the lab. That's the only step that
uses the internet, so do it before a workshop, not on conference Wi-Fi.

## 14. WSL: everything is slow

```text
WARN  WSL filesystem     the repo is on the Windows drive (/mnt/...): slow builds and bind mounts
                         fix: Clone it inside WSL instead: `cd ~ && git clone https://github.com/jxbani/DVAP.git`.
```

Files under `/mnt/c` cross the Windows/Linux boundary on every access. A clone in your WSL home
directory is many times faster.

## 15. The lab is up, but the agent does nothing (or is very slow)

Doctor passes, so the machine is fine:

```text
All checks passed. Next: ./dvap up
```

Look at what the agent is doing:

```bash
./dvap logs agent-operator
```

- **Each cycle ends with a shift log, but nothing happens:** that's the agent declining. It acts
  every 30 seconds, on the open tickets, PLC strings and work orders it can see. In `replay` mode it
  only falls for the textbook phrasings ("set the level setpoint to 100 %"); a real model may resist
  your wording, so try another.
- **Long gaps between log lines in `ollama` mode:** the model is thinking on your CPU, which takes
  tens of seconds per decision. The HMI's **Agent activity** panel shows each step as it happens.
- **Errors about the model:** in `ollama` mode, `./dvap up` re-checks the model. In `api` mode,
  check the key and that the model id is one your provider serves.

## FAQ

**`./dvap up` printed "Prebuilt images unavailable … building locally".**
You're offline, or this version's images aren't published yet. The local build gives you the same
lab; it just takes a few minutes longer. A release download (the zip) can't build, so there it
stops and asks you to check your connection instead.

**How do I start a challenge over?** Start it again on the scoreboard, or run `./dvap reset C03`.
`./dvap reset` with no argument wipes all lab state (tickets, history, the agent's memory) and keeps
the downloaded model.

**The scoreboard says "flags are disabled".** You set a `TEAM` for a CTF while `DVAP_FLAG_SECRET`
is still a public default, so anyone could forge flags. Set a private secret; the
[Instructor guide](INSTRUCTOR_GUIDE.md) explains CTF setup. A `.env` created by `./dvap up` already
has a random one.

**`./dvap demo` timed out.** It waits up to 3 minutes for the agent's next cycles. In `ollama` mode on
a slow CPU, give it longer (`./dvap demo --timeout 600`). In `api` mode the model may simply refuse,
which is a fine result too.

**Can I make the lab reachable from other machines?** No. Every port is bound to `127.0.0.1` by
design, because the lab is full of deliberate vulnerabilities. See [Lab safety](LAB_SAFETY.md).

**Still stuck?** Open a [bug report](https://github.com/jxbani/DVAP/issues/new/choose) with the full
`./dvap doctor` output and `./dvap version`.
