# Lab safety

> [!WARNING]
> **DVAP is deliberately vulnerable software.** It contains working prompt-injection, command
> injection, unauthenticated industrial protocols and an unauthenticated message bus — on purpose.
>
> - Run it **only on a machine you control**, never on a shared server or a cloud host with a public IP.
> - **Never** expose its ports beyond `127.0.0.1`, put it behind a reverse proxy, or port-forward it.
> - **Never** point it at real equipment. Everything here is simulated; nothing in DVAP may connect to a
>   real PLC, a real industrial network, or any host outside the lab's Docker network.
> - Treat anything a participant types into the lab (tickets, PLC strings, bus messages) as hostile.

This page records how the lab is contained and what was checked before release.

## Containment, as configured

| Control | Setting | Where |
|---|---|---|
| Published ports | Only the `gateway` publishes ports: the HMI `127.0.0.1:8080`, ticket form `127.0.0.1:8081` and scoreboard `127.0.0.1:8090`. Nothing binds `0.0.0.0`. The port numbers can be changed (`HMI_PORT`, `CMMS_PORT`, `SCOREBOARD_PORT`); the `127.0.0.1` address is hard-coded and cannot. | `docker-compose.yml` |
| Internal network | Every lab service is on `plant` only, declared `internal: true`: no route to the host or the internet. That includes the three UIs. | `docker-compose.yml` |
| Ingress gateway | Docker can't publish a port from an internal-only network, so a stock reverse proxy (`nginxinc/nginx-unprivileged`, pinned) is the one lab container on `edge`. It forwards each port to one fixed UI on `plant` (`gateway/nginx.conf`); nothing a participant sends changes where it connects. It runs non-root, read-only, with all capabilities dropped. | `docker-compose.yml`, `gateway/nginx.conf` |
| Local LLM | `ollama` is on `plant` only. Models are downloaded by the separate one-shot `ollama-pull` service (`make model`, `setup` profile), the only container with internet access, and only while it runs. | `docker-compose.yml`, `Makefile` |
| Diagnostic sandbox (C05) | `plant` network only; runs as `nobody` (65534); read-only root filesystem with a `tmpfs` `/tmp`; `cap_drop: [ALL]`; `no-new-privileges`; `pids_limit: 128`; `mem_limit: 256m`. | `docker-compose.yml` |
| Privileges | No container is `privileged`; none mounts the Docker socket. The only host paths mounted are `./challenges` (read-only, scoreboard) and `./gateway/nginx.conf` (read-only, gateway). | `docker-compose.yml` |
| Secrets | None in the repo. The flag secret defaults to a public dev value — set `DVAP_FLAG_SECRET` for any real CTF. See `.env.example`. | `.env.example` |

### Why Ollama is not on `edge`

Ollama's API can pull a model from an arbitrary registry. If it shared the internet-facing network,
a participant who gets a shell inside the lab (that is the C05 challenge) could reach
`ollama:11434` and use it as an egress proxy. Keeping it internal closes that path; the
download happens beforehand in a container the lab never talks to.

## Verification performed for this release

Run against the live stack (`make up`):

- `docker compose config`: every published port has host IP `127.0.0.1`; networks are
  `plant` (internal) and `edge`; no `privileged`, no `docker.sock` mounts.
- Routing tables (`/proc/net/route`): `hmi`, `cmms` and `scoreboard` have **no default route**;
  only the `gateway` does. Through the gateway, all three UIs load, a ticket can be posted, and
  the HMI's event streams arrive unbuffered.
- `docker inspect` on the sandbox: `User=65534:65534`, `ReadonlyRootfs=true`, `CapDrop=[ALL]`,
  `SecurityOpt=[no-new-privileges:true]`, `PidsLimit=128`, memory 256 MiB, networks `plant` only.
- Inside the sandbox: writing under `/app` fails (`Read-only file system`); `/tmp` is writable;
  `CapEff: 0000000000000000`.
- The C05 path still works as designed: a `run_diagnostic` injection executed a second command that
  read the PLC's coils over Modbus — confined to the lab network.
- `ollama` is attached to `plant` only and still serves the downloaded model.

Re-check these after changing `docker-compose.yml`:

```bash
docker compose config --format json | python -c "import json,sys; c=json.load(sys.stdin); [print(n, [(p.get('host_ip'), p.get('published')) for p in s.get('ports', [])], sorted(s.get('networks', {}))) for n, s in c['services'].items()]"
docker inspect "$(docker compose ps -q sandbox)" --format '{{.Config.User}} ro={{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}} {{.HostConfig.SecurityOpt}}'
```

## Residual risks (known and accepted)

- **The lab is meant to be broken.** A participant with a shell in the sandbox can reach every
  service on `plant`, including the PLC (Modbus/OPC UA have no authentication) and Redis (no
  password). That is the exercise; it is why the lab must stay on an isolated machine.
- **Hosted models need egress.** The agent runs fully offline with Ollama. Pointing `MODEL` at a
  hosted provider requires giving `agent-operator` an internet-connected network, which also gives
  any code running as the agent a way out. Do that only on a disposable machine.
- **Resource exhaustion.** Only the sandbox has pid/memory limits. A participant can still slow the
  lab down (e.g. flood the ticket form); reset with `make reset`.
- **Other containers run with Docker's default capabilities.** Only the sandbox runs
  attacker-controlled commands by design. The PLC binds Modbus port 502, which needs
  `NET_BIND_SERVICE` if capabilities are dropped; harden further with care.
- **Classroom mode** (`docker compose -p team1 ...`) runs one stack per team on the same host. The
  stacks are isolated from each other by separate networks, but they share the host kernel and
  resources.

## Reporting a real escape

A deliberate vulnerability listed in [VULNERABILITIES.md](VULNERABILITIES.md) is not a bug. A way
to get **out** of the lab — reaching the host or the internet from inside it, or a published port
that isn't loopback-only — is. Please report it privately; see [SECURITY.md](../SECURITY.md).
