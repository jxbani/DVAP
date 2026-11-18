# Release-readiness audit

| | |
|---|---|
| Date | 2026-11-18 |
| Audited | branch `safeenvelope` @ `8b4b956` (2 commits ahead of `main` @ `0a2f909`), plus the running Docker stack built from it |
| Host | Windows 11, Docker Desktop 29.9.3, WSL2 Ubuntu (GNU Make 4.4.1), uv, Python 3.12 |
| Method | Read-only. Nothing was fixed. Every finding below was observed (command output or a live container), except where marked *not executed* or *not tested* |

**Verdict: not ready to publish yet.** There are no leaked secrets and no personal data in any file
or diff, and the containment holds. But four blockers must be fixed first — two of them can't be
undone once the repository is public (see [the prioritised fix list](#prioritised-fix-list)).

---

## 1. Secrets

**gitleaks v8.30.1** (official image `zricethezav/gitleaks:v8.30.1`, already present locally):

| Scan | Scope | Result |
|---|---|---|
| `gitleaks git --log-opts=--all` | Full history: 11 commits, all refs (`main`, `safeenvelope`), ~1.29 MB | **No leaks found** |
| `gitleaks dir` | Working tree as shipped: `git archive HEAD`, 134 tracked files, ~1.28 MB (`.venv` excluded) | **No leaks found** |

gitleaks skips low-entropy literals, so I also grepped every tracked file for
`secret|password|token|api_key =`. Every hit is intentional:

| Finding | Location | Assessment |
|---|---|---|
| Public default flag-signing secret `dvap-dev-secret` | `docker-compose.yml:81`, `services/scoreboard/scoreboard/api.py:29` | Not a leak, but **anyone can mint valid flags for any team** unless the instructor sets `DVAP_FLAG_SECRET`. Only the instructor guide warns about it. |
| Placeholder `DVAP_FLAG_SECRET=change-me` | `.env.example:10` | Fine (template). |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` pass-through, empty by default | `docker-compose.yml:161-162` | Fine: no value committed. |

Ignored local files present on the audit machine: `.gstack/`, `.impeccable/`, `results/` — local
tool state and generated reports, none tracked. There is no `.env` file.

## 2. Exposure

| Requirement | Status | Evidence |
|---|---|---|
| Every published port binds `127.0.0.1` | **Pass** | `docker-compose.yml:58` (cmms), `:72` (hmi), `:94` (scoreboard). The IP is a literal in the file; only the port number can be changed. Enforced by `tests/test_lab_safety.py`. No other service publishes a port (`docker compose config`). |
| Vulnerable services on internal-only networks | **Partial** | `plant` is `internal: true` (`docker-compose.yml:209`), and every service is on it. But **`cmms` — the C01 vulnerable ticket service — also joins the non-internal `edge` network** (`:57`), as do `hmi` (`:71`, which relays untrusted bus messages) and `scoreboard` (`:93`). `edge` exists only so these ports can be published, but it also gives those three containers **outbound internet access**. None of them fetches a URL a participant controls, so it isn't exploitable as-is, but it doesn't meet "internal-only". |
| Sandbox: no external network | **Pass** | Only on `plant` (`:102`). Live: its routing table holds just the local subnet (`000019AC`, 172.25.0.0/16) with **no default route**. |
| Sandbox: capabilities dropped | **Pass** | `cap_drop: [ALL]` (`:107`), `no-new-privileges` (`:108`). Live `docker inspect`: `CapDrop=[ALL]`; `CapEff: 0000000000000000` verified in-container on the earlier run. |
| Sandbox: read-only root fs | **Pass** | `read_only: true`, `tmpfs: /tmp` (`:105-106`). Live: `ReadonlyRootfs=true`; writing under `/app` fails. |
| Sandbox: non-root | **Pass** | `user: "65534:65534"` (`:104`). Live: `uid=65534(nobody)`. |

Also observed:

- **12 of 13 containers run as root** (no `user:`; `docker compose exec <svc> id -u` → `0`). Only
  the sandbox was required to be non-root; the Redis image drops to its own user in its entrypoint.
- **LiteLLM tries to reach the internet from inside the lab.** At startup it fetches its model price
  map from `raw.githubusercontent.com` (litellm 1.109.1, `litellm/__init__.py:411-421`) unless
  `LITELLM_LOCAL_MODEL_COST_MAP=True`, which nothing in the repo sets. Live `agent-operator` logs show
  3 attempts with back-off (`Temporary failure in name resolution`), then a fallback to its bundled
  copy. The internal network blocks it, which proves containment works, but it is still an outbound
  connection attempt that CLAUDE.md's hard rules forbid, and it delays startup by ~7 s. The same
  fetch *succeeds* when `dvap bench` runs a real model on the host.
- No `privileged` containers and no Docker-socket mounts (`tests/test_lab_safety.py`).

## 3. Reproducibility

| Finding | Location | Notes |
|---|---|---|
| Python base image is a floating tag with no digest | `Dockerfile:3` `ghcr.io/astral-sh/uv:python3.12-bookworm-slim` | Python patch version, Debian packages and the bundled `uv` all change underneath a rebuild. |
| `redis:7-alpine` has no digest and floats across minor versions | `docker-compose.yml:42` | It currently resolves to **Redis 7.4.11** — the minor version that changed Redis's licence (see §6). |
| `ollama/ollama:latest` used twice | `docker-compose.yml:184`, `:200` | Running version observed: 0.40.16. |
| The model is a mutable tag | `docker-compose.yml:156` (`MODEL`), `ollama-pull` command (`:205`) | `qwen2.5:7b-instruct` can be re-pointed upstream; there is no digest. |
| Runtime download: the model | `make model` (`Makefile:12`) | Expected and documented (~4.7 GB, setup profile only). |
| Runtime download: LiteLLM price map | §2 | Undocumented; attempted on every agent start. |
| Runtime download: Chart.js CDN fallback | `bench/report.py:61` | Used only if the vendored file is missing, and pins **4.4.1** while the vendored copy is **4.4.9**. |
| Python dependencies: lower bounds only | `pyproject.toml:8-19` | **Mitigated:** `uv.lock` pins exact versions and hashes, and images build with `uv sync --frozen` (`Dockerfile:8`). |
| Build backend unpinned | `pyproject.toml:25` `requires = ["hatchling"]` | Affects only the local `dvap` CLI build. |
| GitHub Actions pinned by tag, not commit SHA | `.github/workflows/ci.yml:20-21,33-34,47`, `weekly-solvers.yml:19-20,31` | `setup-uv` also installs whatever `uv` is latest (no `version:`). |
| Weekly job deliberately upgrades deps | `weekly-solvers.yml:24` `uv sync --upgrade` | Intentional drift detection; documented in the workflow. |

The plant physics is deterministic, and the benchmark logs seeds, model ids/versions and the exact
prompts.

## 4. Portability

| Platform | Finding | Evidence |
|---|---|---|
| **Windows (any) with `core.autocrlf=true`** | **No `.gitattributes`.** A Windows checkout gets CRLF line endings, and they are copied into the Linux images. **The running sandbox image's diagnostic scripts contain carriage returns** (4 CR bytes in each of `ping_plc.sh` and `sensor_check.sh`). They work today only because they are trivial (`ping_plc.sh:4` ends in `...sandbox)"\r`); any `if`/`then` or argument parsing added later will break on Windows checkouts only. | `git ls-files --eol`: `i/lf w/crlf` for `*.sh`, `Makefile`, `Dockerfile`, `docker-compose.yml`; CR bytes counted inside the sandbox container |
| **Windows WSL2** | The Makefile itself is fine: GNU Make 4.4.1 strips the CR from recipe lines (`make -n up` under WSL prints `docker compose up -d --build` with no `^M`, *tested*). The script issue above still applies when the clone lives on the Windows side. | WSL Ubuntu dry run |
| **Native Windows / Linux without `make`** | `make` is required by the README quickstart but is absent by default on Windows (absent on the audit host) and on minimal Linux. The README gives no `docker compose` equivalents, and `make reset CH=…` also needs `curl` (`Makefile:34`). | `make: command not found` on the host |
| **macOS Apple Silicon** | *Not tested on hardware.* No arm64 blocker found: all base images are multi-arch, and `uv.lock` has 228 linux-aarch64 + 111 macOS-arm64 wheels with **no source-only packages** to compile. But Ollama in Docker on macOS gets **no GPU** (no Metal in containers), so a 7B model runs on CPU inside the VM, and the agent can't use a native (Metal) Ollama on the host, because the lab network is internal by design. Expect minutes per agent decision. | `uv.lock` wheel scan; compose networks |
| **Any Docker Desktop (macOS/Windows)** | "~8 GB of free RAM" (`README.md:20`) isn't the binding limit: what matters is the memory **allocated to Docker Desktop's VM**, which is often below what the 4.7 GB model plus 12 services need. | README text vs. Docker Desktop defaults |
| **Any OS** | `dvap bench` must be run from the repo root: `bench/runner.py:21` (`challenges`), `bench/report.py:10-11` (Chart.js path, `README.md`) resolve against the current directory. | Code inspection |
| **Any OS** | **`make reset` deletes the downloaded model.** `docker compose down -v` (`Makefile:31`) removes every volume declared in the compose file, including `ollama-models`, contradicting the comment at `docker-compose.yml:216` ("kept across `make reset`"). The next `make model` re-downloads 4.7 GB. | `docker compose config --volumes` lists `ollama-models`; Docker's documented `-v` behaviour (*not executed*, destructive) |

## 5. Personal data

| Check | Result |
|---|---|
| Hard-coded local paths (`C:\Users\…`, `/home/…`, `/Users/…`, `Desktop\`) | None in tracked files or in any diff in the full history (including deleted content). |
| Usernames / real names | None in files or diffs. Seed tickets (`services/cmms/cmms/seed.py`) use equipment tags only; the plant ("Al-Waha") is fictional. |
| Email addresses in files | None (the only emails anywhere are `noreply@anthropic.com` in commit trailers). |
| IP addresses | Only `127.0.0.1` and `0.0.0.0`. |
| **Commit metadata** | **All 11 commits carry the author's git name and a personal Gmail address as both author and committer.** Making the repo public publishes this permanently, and a later history rewrite won't remove it from forks or caches. |
| Placeholder identity | `CITATION.cff:11` and the licence use "The DVAP Authors"; no personal name added. |

## 6. Licensing

The project is Apache-2.0 (`LICENSE`, `pyproject.toml`). 94 Python packages are locked: **82 at
runtime** (in the images, `uv export --no-dev`) and 12 dev-only. Licences were read from each
installed package's metadata; the full table is in the [appendix](#appendix-a-python-dependency-licences).

**Nothing is incompatible with Apache-2.0** for distributing this repository's source. Items to review:

| Component | Licence | Shipped where | Assessment |
|---|---|---|---|
| `asyncua` 2.1.0 | **LGPL-3.0-or-later** | runtime (plc) | Compatible as an unmodified dependency imported at runtime. **If you publish built images**, the LGPL obligations apply (licence text plus access to its source, which PyPI provides). |
| **Redis server 7.4.11** (`redis:7-alpine`) | **RSALv2 / SSPLv1** (source-available, *not* OSI open source, since 7.4) | pulled image, not redistributed | Not an incompatibility for the source repo, but it makes the default stack depend on non-OSI software, and the floating tag hid the change. **Valkey** (BSD-3) or `redis:7.2` (BSD-3) would avoid it. |
| `certifi`, `tqdm` (runtime); `pathspec` (dev) | MPL-2.0 (file-level copyleft) | runtime/dev | Fine unmodified. |
| `litellm` 1.109.1 | MIT, except a repo-level `enterprise/` directory | runtime (agent) | The wheel ships only `litellm/proxy/enterprise_billing`, which is outside that directory and has no separate licence. Fine. |
| `httpx2-jsfetch` | unknown | **never installed** | A Pyodide-only dependency (`sys_platform == 'emscripten'`, `uv.lock:973`). Not applicable. |
| Chart.js 4.4.9 + `@kurkle/color` 0.3.2 (vendored) | MIT | `services/hmi/hmi/static/vendor/chart.umd.min.js` | The licence notices are kept in the file. There is no NOTICE / third-party list. |
| Ollama 0.40.16 | MIT | pulled image | Fine. |
| Model `qwen2.5:7b-instruct` | Apache-2.0 (`ollama show --license`) | downloaded by `make model` | Fine. Other Qwen2.5 sizes use the Qwen licence, so switching `OLLAMA_MODEL` can change this. |
| Debian/Alpine base layers | various (incl. GPL system packages) | images | Normal for container images; relevant only if you publish images. |

## 7. Documentation gaps (README, for a first-time user)

1. **The clone URL is a placeholder**: `https://github.com/OWNER/dvap.git` (`README.md:23`, also
   `docs/INSTRUCTOR_GUIDE.md:15`). The quickstart fails as written.
2. **Broken hero image**: `docs/media/demo.gif` doesn't exist (`README.md:15-16`).
3. **How to attack the internal services.** Five challenges (C01b, C03, C05, C07, C08) need a shell on
   the lab network (`docker compose exec plc|bus|hmi …`). This is explained only in the instructor guide; a
   solo learner reading the README has no way in.
4. **How to try the defended mode** (`make defend` / `make undefend`): absent from the README, although
   the README's results section talks about defended runs.
5. **Platform notes**: nothing on Windows (no `make`, line endings), WSL2, or macOS (CPU-only model,
   Docker Desktop memory allocation).
6. **Commands without `make`**: no `docker compose` equivalents for `up`, `model`, `reset`, `defend`.
7. **What to expect on first run / troubleshooting**: how long an agent decision takes, what happens
   if `make up` runs before `make model` (the agent errors every cycle until the model exists), where
   to look (HMI agent panel, `docker compose logs agent-operator`), port clashes (`HMI_PORT` etc. are
   only in `.env.example`).
8. **Using a hosted model**: `MODEL` / API keys exist in compose, but the README doesn't say how, or
   that it needs egress (only `docs/LAB_SAFETY.md` does).
9. **Cleanup**: how to remove the lab, and that `make reset` currently deletes the 4.7 GB model (§4).
10. **Requirements**: `uv` (needed for `make test` and `make bench`) isn't listed; neither is "Docker
    memory ≥ 8 GB".
11. No CHANGELOG / release notes / version tag for 0.1.0.
12. `CODE_OF_CONDUCT.md:66` still says `[INSERT CONTACT METHOD]`.

## 8. Test gaps

All 11 challenges have an automated solver (`tests/test_solvers.py`) and a benchmark scenario
(`bench/scenarios.py`). 172 tests pass. Gaps:

| Gap | Where | Why it matters |
|---|---|---|
| **No test runs the composed stack.** | — (`tests/test_lab_safety.py` only parses the YAML) | The previous change found a live-only bug (the guard toggle and C10 scheduled tasks reset on every MCP request) that 164 passing in-process tests missed. CI's `docker compose build` doesn't start anything. A smoke test (`up`, health, one MCP call with the guard on) would catch this class of bug. |
| **`maintenance-planner` has no tests at all.** | `services/maintenance-planner/maintenance_planner/api.py:34,40,49,63` | It breaks the CLAUDE.md rule that every service has unit tests. The C07 solver drives the bus with a fake Redis, not this service. |
| `agent-operator` HTTP API untested | `services/agent-operator/agent_operator/api.py` (`/chat`, `/approve`, `/approvals`, lifespan, cycle loop) | The scoreboard's busy human (C09) depends on these endpoints. |
| Scoreboard background tasks untested | `services/scoreboard/scoreboard/api.py:95` (`_busy_human`), `:112` (`checker.run` Redis subscription) | Live-only paths for C09 and for all scoring. |
| vendor-analytics HTTP routes untested | `services/vendor-analytics/vendor_analytics/server.py:59` (`/rugpull`), `:66` (`/reset`) | Tests call `_set_description` directly; the route participants actually use is untested. |
| C01b has no dedicated defended test | `tests/test_safeenvelope.py` | Covered only indirectly, via `tests/test_bench.py`'s guard-on run. |
| Real-model path untested | `LiteLLMClient` (`services/agent-operator/agent_operator/llm.py`), `dvap bench` with a non-fake model | Only the deterministic fakes run in CI. That's acceptable, but token accounting and provider errors are unexercised. |
| `dvap` CLI entry point untested | `bench/cli.py` | Argument parsing and `--challenges` filtering. |
| HMI front end untested | `services/hmi/hmi/static/app.js` (including the SafeEnvelope panel) | No JS tests. |
| Runtime hardening checked statically only | `tests/test_lab_safety.py` | The live checks (read-only fs, `CapEff=0`, no default route) were done by hand in this audit. |

---

## Prioritised fix list

### Blocker — fix before the repository goes public

1. **Merge the release into `main`.** `main` (`0a2f909`) has no README, LICENSE, SECURITY or
   SafeEnvelope; everything is on `safeenvelope` (`8b4b956`). If `main` is the default branch, publishing
   now ships an unlicensed repo with no safety warnings.
2. **Decide on the commit email before publishing** (§5). This can't be undone after the repo goes
   public. Options: rewrite history to a GitHub `noreply` address, or publish a fresh squashed history.
3. **Replace the placeholders**: `OWNER` (`README.md:23`, `docs/INSTRUCTOR_GUIDE.md:15`), and the
   Code of Conduct contact (`CODE_OF_CONDUCT.md:66`). The quickstart doesn't work and the CoC can't be
   enforced as shipped.
4. **Stop the LiteLLM outbound fetch** (§2): set `LITELLM_LOCAL_MODEL_COST_MAP=True` for
   `agent-operator` (and for `dvap bench`). The project's first hard rule forbids connections outside
   the lab network, and the code currently attempts one on every agent start.

### Should — fix for a credible first release

5. Fix **`make reset` deleting the model volume** (`Makefile:31` vs `docker-compose.yml:216`): remove
   the lab's volumes by name instead of `down -v`, or correct the comment and warn in the README.
6. Add **`.gitattributes`** (`* text=auto eol=lf`, at least `*.sh` and `Dockerfile`) so Windows
   checkouts don't put CRLF into Linux images (§4).
7. **Fail closed on the default flag secret**: refuse to mint or verify flags when `TEAM` isn't `solo`
   and `DVAP_FLAG_SECRET` is the public default (`scoreboard/api.py:29`).
8. **Pin images**: the base image by digest (`Dockerfile:3`), and replace `ollama/ollama:latest`
   (`docker-compose.yml:184,200`) and `redis:7-alpine` (`:42`) with digests. Prefer **Valkey or
   Redis 7.2** to keep the stack OSI-licensed (§6).
9. **Get vulnerable services off the egress network**: put an ingress-only reverse proxy on `edge`
   in front of `cmms`/`hmi`/`scoreboard` (keeping those three internal-only), or disable masquerading
   on `edge` after testing on Docker Desktop.
10. **README additions** (§7 items 3–10): attacker access, defended mode, platform notes and
    Docker memory, `docker compose` equivalents of the `make` targets, troubleshooting, hosted models,
    cleanup, `uv`. Record or remove the demo GIF.
11. **Tests**: a compose smoke test in CI (start the stack, check health, one guarded MCP call);
    unit tests for `maintenance-planner`; the agent-operator HTTP API; the vendor `/rugpull` route.
12. **Pin GitHub Actions** to commit SHAs and set an explicit `uv` version in `setup-uv`.

### Nice-to-have

13. Add a NOTICE / third-party file (vendored Chart.js 4.4.9, image and model licences, the LGPL
    note for `asyncua` if you publish images).
14. Run the other 12 containers as non-root where possible (the PLC needs `NET_BIND_SERVICE` for port 502).
15. Make `dvap bench` work from any directory (resolve paths from the package, not the cwd).
16. Align or drop the CDN fallback in `bench/report.py:61` (4.4.1 vs vendored 4.4.9); pin `hatchling`.
17. A dedicated defended test for C01b; tests for scoreboard background tasks, the `dvap` CLI and the HMI JS.
18. A CHANGELOG and a `v0.1.0` tag; ignore `.impeccable/` in the repo's `.gitignore` (it is ignored
    only by local configuration today).

---

## Appendix A: Python dependency licences

From installed package metadata (`License-Expression`, else trove classifiers). "(dev)" marks
dev-only packages, which are not in the images.

| Licence | Packages |
|---|---|
| MIT | annotated-doc, annotated-types, anyio, ast-serialize (dev), attrs, charset-normalizer, fastapi, filelock, h2, hpack, httpx-sse, iniconfig (dev), jiter, jsonschema, jsonschema-specifications, librt (dev), litellm, mypy (dev), mypy-extensions (dev), pydantic, pydantic-core, pydantic-settings, pyjwt, pytest (dev), redis, referencing, rpds-py, ruff (dev), truststore, typing-inspection, urllib3, zipp, aiosqlite, h11, hyperframe, jmespath, mcp, pluggy (dev), pytz, pyyaml, six, tiktoken |
| MIT-0 | cffi |
| Apache-2.0 | aiosignal, boto3, botocore, frozenlist, hf-xet, huggingface-hub, importlib-metadata, multidict, openai, opentelemetry-api, propcache, pytest-asyncio (dev), python-multipart, requests, s3transfer, sortedcontainers, tokenizers, types-pyyaml (dev), yarl |
| Apache-2.0 AND MIT | aiohttp |
| Apache-2.0 AND CNRI-Python | regex |
| Apache-2.0 OR BSD-3-Clause | cryptography |
| Apache-2.0 OR BSD-2-Clause | packaging |
| MIT OR Apache-2.0 | sniffio |
| BSD-3-Clause | click, fsspec, httpcore, httpcore2, httpx2, idna, markupsafe, pycparser, python-dotenv, sse-starlette, starlette, uvicorn |
| BSD (unspecified variant) | colorama, fastuuid, httpx, jinja2, pymodbus |
| BSD-2-Clause | pygments (dev) |
| BSD OR Apache-2.0 | python-dateutil |
| PSF-2.0 | aiohappyeyeballs, pywin32 (Windows only), typing-extensions |
| **MPL-2.0** | certifi, pathspec (dev) |
| **MPL-2.0 AND MIT** | tqdm |
| **LGPL-3.0-or-later** | asyncua |
| not installed (emscripten only) | httpx2-jsfetch |

## Appendix B: how to reproduce this audit

```bash
# secrets (official gitleaks image)
docker run --rm -v "$PWD:/repo:ro" --entrypoint sh zricethezav/gitleaks:v8.30.1 \
  -c "git config --global --add safe.directory '*' && gitleaks git /repo --log-opts='--all' --redact"
mkdir -p /tmp/tree && git archive HEAD | tar -x -C /tmp/tree
docker run --rm -v /tmp/tree:/tree:ro zricethezav/gitleaks:v8.30.1 dir /tree --redact

# exposure
uv run pytest tests/test_lab_safety.py
docker inspect "$(docker compose ps -q sandbox)" --format '{{.Config.User}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.CapDrop}}'
docker compose exec sandbox cat /proc/net/route        # no 00000000 destination = no default route

# line endings, runtime fetches, licences
git ls-files --eol -- '*.sh' Dockerfile Makefile
docker compose logs agent-operator | grep -i "model cost map"
uv export --frozen --no-dev --no-hashes   # runtime dependency set
```
