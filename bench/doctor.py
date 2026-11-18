"""`dvap doctor`: can this machine run DVAP? Every failed check comes with the exact fix.

Standard library only (like the rest of the lifecycle CLI) so it runs before any `uv sync`.
The probes are module-level functions so the tests can swap in a fake machine.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_DOCKER = (24, 0)
MIN_COMPOSE = (2, 20)  # `up --wait`, profiles from .env
GB = 1024**3
# Memory Docker must be able to give the lab, and free disk for images (+ the model), per mode.
NEEDS = {"replay": (4, 6), "api": (4, 6), "ollama": (8, 12)}
PORTS = (("HMI_PORT", 8080), ("CMMS_PORT", 8081), ("SCOREBOARD_PORT", 8090))
KEY_FOR = {"anthropic/": "ANTHROPIC_API_KEY"}  # anything else LiteLLM routes with OPENAI_API_KEY


@dataclass
class Check:
    name: str
    status: str  # PASS | WARN | FAIL
    detail: str
    fix: str = ""


# --- probes (patched in tests) -------------------------------------------


def sh(*cmd: str) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, str(e)
    return p.returncode, (p.stdout or p.stderr).strip()


def docker_info() -> dict | str:
    """Docker's own view (on macOS/Windows: the VM's memory and arch). A str is the error."""
    if not shutil.which("docker"):
        return "docker not found"
    rc, out = sh("docker", "info", "--format", "{{json .}}")
    try:
        info = json.loads(out.splitlines()[0])  # still JSON when only the daemon is down
    except (ValueError, IndexError):
        return out or "docker info failed"
    if rc == 0 and info.get("ServerVersion"):
        return info
    return "Docker is not running: " + str((info.get("ServerErrors") or ["daemon not reachable"])[0])


def compose_version() -> str | None:
    rc, out = sh("docker", "compose", "version", "--short")
    return out.lstrip("v") if rc == 0 else None


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def dvap_running() -> bool:
    rc, out = sh("docker", "compose", "--project-directory", str(ROOT), "ps", "-q", "gateway")
    return rc == 0 and bool(out)


def volume_exists(name: str) -> bool:
    return sh("docker", "volume", "inspect", name)[0] == 0


def disk_free(path: str) -> int:
    return shutil.disk_usage(path if os.path.isdir(path) else str(ROOT)).free


def host() -> tuple[str, str, str]:
    """(system, machine, kernel release); release says 'microsoft' under WSL."""
    return platform.system(), platform.machine(), platform.release()


# --- checks --------------------------------------------------------------


def version(text: str | None) -> tuple[int, ...]:
    m = re.search(r"\d+(?:\.\d+)*", text or "")
    return tuple(int(x) for x in m.group(0).split(".")) if m else ()


def install_docker_fix(system: str, wsl: bool) -> str:
    if wsl:
        return "Install Docker Desktop on Windows and enable Settings > Resources > WSL integration for this distro."
    if system == "Linux":
        return "Install Docker Engine + the Compose plugin: https://docs.docker.com/engine/install/"
    return "Install Docker Desktop: https://docs.docker.com/desktop/"


def memory_fix(system: str, wsl: bool, need: int) -> str:
    if wsl or system == "Windows":
        return (f"Give WSL at least {need} GB: in %UserProfile%\\.wslconfig set [wsl2] memory={need}GB, "
                "then run `wsl --shutdown` and restart Docker Desktop.")
    if system == "Darwin":
        return f"Docker Desktop > Settings > Resources > Memory: set at least {need} GB, then Apply & restart."
    return f"This machine has less than {need} GB of RAM: free memory, or use DVAP_LLM_MODE=replay or api."


def run_checks(env: dict[str, str], mode: str, project: str) -> list[Check]:
    system, machine, release = host()
    wsl = system == "Linux" and "microsoft" in release.lower()
    checks: list[Check] = []

    info = docker_info()
    if isinstance(info, str):
        missing = "not found" in info
        fix = install_docker_fix(system, wsl) if missing else (
            "Start Docker Desktop and wait until it says it is running." if system != "Linux" or wsl else
            "Start it: `sudo systemctl start docker`. If it is 'permission denied': "
            "`sudo usermod -aG docker $USER`, then log out and back in.")
        checks.append(Check("Docker", "FAIL", info.splitlines()[0][:100], fix))
        return checks  # everything below needs Docker
    have = version(info.get("ServerVersion"))
    ok = have >= MIN_DOCKER
    checks.append(Check("Docker", "PASS" if ok else "FAIL", f"Engine {info.get('ServerVersion')} (need {'.'.join(map(str, MIN_DOCKER))}+)",
                        "" if ok else "Update Docker. " + install_docker_fix(system, wsl)))

    cv = compose_version()
    ok = version(cv) >= MIN_COMPOSE
    checks.append(Check("Docker Compose", "PASS" if ok else "FAIL",
                        f"v{cv} (need v{'.'.join(map(str, MIN_COMPOSE))}+)" if cv else "the `docker compose` plugin is missing",
                        "" if ok else "Install/update the Compose v2 plugin: https://docs.docker.com/compose/install/"))

    need_mem, need_disk = NEEDS[mode]
    mem = int(info.get("MemTotal") or 0) / GB
    ok = mem >= need_mem * 0.95  # Docker reports a little less than what was allocated
    checks.append(Check("Memory for Docker", "PASS" if ok else "FAIL", f"{mem:.1f} GB (need {need_mem} GB for {mode} mode)",
                        "" if ok else memory_fix(system, wsl, need_mem)))

    free = disk_free(info.get("DockerRootDir", "")) / GB
    ok = free >= need_disk
    checks.append(Check("Free disk", "PASS" if ok else "FAIL", f"{free:.0f} GB free (need {need_disk} GB for {mode} mode)",
                        "" if ok else "Free some space, e.g. `docker system prune` removes unused images and build cache."))

    arch = info.get("Architecture", machine)
    known = arch.lower() in ("x86_64", "amd64", "aarch64", "arm64")
    label = {"Darwin": " (Apple Silicon)" if arch in ("aarch64", "arm64") else " (Intel Mac)"}.get(system, "")
    checks.append(Check("CPU architecture", "PASS" if known else "FAIL", f"{arch}{label}; DVAP images are amd64 + arm64",
                        "" if known else "Use an x86_64 or arm64 machine: DVAP publishes no images for this architecture."))

    running = None
    for var, default in PORTS:
        port = int(env.get(var) or default)
        if port_free(port):
            checks.append(Check(f"Port {port}", "PASS", f"free ({var})"))
            continue
        running = dvap_running() if running is None else running
        if running:
            checks.append(Check(f"Port {port}", "PASS", "in use by DVAP's gateway (the lab is up)"))
        else:
            find = f"netstat -ano | findstr :{port}" if system == "Windows" else f"lsof -i :{port}"
            checks.append(Check(f"Port {port}", "FAIL", f"in use by another program ({var})",
                                f"Stop it (find it with `{find}`) or set {var}={port + 10000} in .env."))

    checks.append(llm_check(env, mode, project))

    if wsl and ROOT.as_posix().startswith("/mnt/"):
        checks.append(Check("WSL filesystem", "WARN", "the repo is on the Windows drive (/mnt/...): slow builds and bind mounts",
                            "Clone it inside WSL instead: `cd ~ && git clone https://github.com/jxbani/DVAP.git`."))
    return checks


def llm_check(env: dict[str, str], mode: str, project: str) -> Check:
    model = env.get("MODEL", "")
    if mode == "replay":
        return Check("LLM mode", "PASS", "replay: recorded responses, no model needed")
    if mode == "api":
        var = next((v for p, v in KEY_FOR.items() if model.startswith(p)), "OPENAI_API_KEY")
        if os.environ.get(var) or env.get(var):
            return Check("LLM mode", "PASS", f"api: {model}, {var} is set")
        return Check("LLM mode", "FAIL", f"api: {model}, but {var} is empty",
                     f"Put your key in .env: {var}=... (or rerun `./dvap up --mode api`).")
    if volume_exists(f"{project}_ollama-models"):
        return Check("LLM mode", "PASS", f"ollama: {env.get('OLLAMA_MODEL')} (model volume present; `up` verifies the model)")
    return Check("LLM mode", "WARN", f"ollama: {env.get('OLLAMA_MODEL')} not downloaded yet",
                 "`./dvap up` downloads it once (~4.7 GB for the default model).")


def report(checks: list[Check]) -> str:
    width = max(len(c.name) for c in checks)
    lines = [f"{'':4}  {'CHECK':<{width}}  DETAIL", f"{'':4}  {'-' * width}  {'-' * 40}"]
    for c in checks:
        lines.append(f"{c.status:<4}  {c.name:<{width}}  {c.detail}")
        if c.fix:
            lines.append(f"{'':4}  {'':<{width}}  fix: {c.fix}")
    failed = sum(c.status == "FAIL" for c in checks)
    lines.append("")
    warned = sum(c.status == "WARN" for c in checks)
    if failed:
        lines.append(f"{failed} check(s) failed.")
    elif warned:
        lines.append(f"No failures ({warned} warning(s): see above). Next: ./dvap up")
    else:
        lines.append("All checks passed. Next: ./dvap up")
    return "\n".join(lines)
