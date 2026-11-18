"""The containment rules from docs/LAB_SAFETY.md, checked against docker-compose.yml so a change
cannot quietly widen the lab (no Docker needed to run this)."""

import os
import re
import tomllib
from pathlib import Path

import yaml

COMPOSE = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
BUILDS = yaml.safe_load(Path("docker-compose.build.yml").read_text(encoding="utf-8"))["services"]
SETUP_ONLY = {"ollama-pull"}  # one-shot model download, `setup` profile, never part of the running lab


def nets(svc: dict) -> set[str]:
    return set(svc.get("networks", []))  # works for the list form and the mapping form


def test_published_ports_are_loopback_only():
    for name, svc in SERVICES.items():
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port!r} beyond loopback"


def test_only_the_gateway_publishes_ports():
    assert {n for n, s in SERVICES.items() if s.get("ports")} == {"gateway"}
    assert len(SERVICES["gateway"]["ports"]) == 3  # HMI, ticket form, scoreboard


def test_lab_network_is_internal_and_every_lab_service_is_on_it():
    assert COMPOSE["networks"]["plant"].get("internal") is True
    for name, svc in SERVICES.items():
        if name not in SETUP_ONLY:
            assert "plant" in nets(svc), f"{name} is not on the internal plant network"


def test_no_vulnerable_service_touches_the_internet_facing_network():
    """Only the gateway (a stock reverse proxy) and the one-shot model download are on `edge`;
    every vulnerable service, the UIs included, is internal-only."""
    on_edge = {n for n, s in SERVICES.items() if "edge" in nets(s)}
    assert on_edge == {"gateway"} | SETUP_ONLY
    for ui in ("hmi", "cmms", "scoreboard"):
        assert nets(SERVICES[ui]) == {"plant"}


def test_gateway_is_hardened_and_only_forwards_to_the_three_uis():
    gw = SERVICES["gateway"]
    assert gw["read_only"] is True and gw["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in gw["security_opt"]
    conf = Path("gateway/nginx.conf").read_text(encoding="utf-8")
    upstreams = set(re.findall(r"set \$upstream http://([a-z-]+):8000;", conf))
    assert upstreams == {"hmi", "cmms", "scoreboard"}
    assert conf.count("proxy_pass") == 3  # no other forwarding target


def test_model_download_is_separated_from_the_lab():
    assert SERVICES["ollama-pull"]["profiles"] == ["setup"]
    assert nets(SERVICES["ollama-pull"]) == {"edge"}
    assert nets(SERVICES["ollama"]) == {"plant"}


def test_sandbox_is_hardened():
    sb = SERVICES["sandbox"]
    assert nets(sb) == {"plant"}
    assert sb["read_only"] is True
    assert sb["cap_drop"] == ["ALL"]
    assert "no-new-privileges:true" in sb["security_opt"]
    assert sb["user"] != "0" and not str(sb["user"]).startswith("0:")
    assert sb.get("pids_limit") and sb.get("mem_limit")


def test_scripts_copied_into_images_have_no_carriage_returns():
    """A CRLF checkout (Windows, core.autocrlf) must not put \\r into Linux containers;
    .gitattributes forces LF."""
    scripts = list(Path("services").rglob("*.sh"))
    assert scripts
    for script in scripts:
        assert b"\r" not in script.read_bytes(), f"{script} has CRLF line endings"


def test_images_are_pinned():
    """Reproducible builds: third-party images by digest, DVAP's own images by DVAP_VERSION, no
    floating :latest anywhere."""
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "@sha256:" in next(line for line in dockerfile.splitlines() if line.startswith("FROM "))
    version = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    for name, svc in SERVICES.items():
        image = svc["image"]
        assert ":latest" not in image, f"{name} floats on :latest"
        if name in BUILDS:
            assert image == f"${{DVAP_REGISTRY:-ghcr.io/jxbani}}/dvap-{name}:${{DVAP_VERSION:-{version}}}", name
        else:
            assert "@sha256:" in image, f"{name} third-party image is not pinned by digest"


def test_build_override_and_release_workflow_cover_the_same_images():
    """docker-compose.yml pulls; docker-compose.build.yml only adds `build:` to the same services;
    the release workflow publishes exactly those, built the same way."""
    assert not any("build" in svc for svc in SERVICES.values())  # the default path never builds
    assert all(set(svc) == {"build"} for svc in BUILDS.values())
    jobs = yaml.safe_load(Path(".github/workflows/release.yml").read_text(encoding="utf-8"))["jobs"]
    published = {s["name"]: (s["package"], s["module"]) for s in jobs["images"]["strategy"]["matrix"]["service"]}
    built = {n: (b["build"]["args"]["PACKAGE"], b["build"]["args"].get("MODULE", "api")) for n, b in BUILDS.items()}
    assert published == built


def test_api_mode_override_only_lets_the_agent_out():
    """`--mode api` adds docker-compose.api.yml: the agent (and nothing else) joins `edge`."""
    api = yaml.safe_load(Path("docker-compose.api.yml").read_text(encoding="utf-8"))["services"]
    assert api == {"agent-operator": {"networks": ["plant", "edge"]}}


def test_github_actions_are_pinned_to_commits():
    """A moved tag can't change what CI runs: every action by full commit SHA, uv by version."""
    for wf in Path(".github/workflows").glob("*.yml"):
        for job in yaml.safe_load(wf.read_text(encoding="utf-8"))["jobs"].values():
            for step in job["steps"]:
                if "uses" in step:
                    assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", step["uses"]), f"{wf.name}: {step['uses']}"
                    if "setup-uv" in step["uses"]:
                        assert step.get("with", {}).get("version"), f"{wf.name}: setup-uv without a uv version"


def test_make_reset_keeps_the_downloaded_model():
    """`down -v` would delete the 4.7 GB model volume; reset removes an explicit allowlist instead,
    which must cover every other named volume (or a new one would silently survive resets)."""
    lines = Path("Makefile").read_text(encoding="utf-8").splitlines()
    recipes = [line for line in lines if line.startswith("\t")]  # commands, not comments
    assert not any("down -v" in r or "down --volumes" in r for r in recipes)
    allowlist = next(line for line in lines if line.startswith("LAB_STATE_VOLUMES"))
    assert set(allowlist.split("=", 1)[1].split()) == set(COMPOSE["volumes"]) - {"ollama-models"}
    from bench.ops import LAB_STATE_VOLUMES  # `./dvap reset` uses the same allowlist

    assert set(LAB_STATE_VOLUMES) == set(COMPOSE["volumes"]) - {"ollama-models"}


def test_litellm_never_fetches_catalogs_on_its_own():
    """The agent must not reach outside the lab (CLAUDE.md hard rule): LiteLLM's self-initiated
    downloads are disabled before it can be imported."""
    import agent_operator.llm  # noqa: F401

    assert os.environ["LITELLM_OFFLINE_MODE"] == "true"


def test_no_privileged_containers_or_docker_socket():
    for name, svc in SERVICES.items():
        assert not svc.get("privileged"), f"{name} is privileged"
        assert "docker.sock" not in str(svc.get("volumes", [])), f"{name} mounts the Docker socket"
