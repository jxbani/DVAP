"""The containment rules from docs/LAB_SAFETY.md, checked against docker-compose.yml so a change
cannot quietly widen the lab (no Docker needed to run this)."""

import os
from pathlib import Path

import yaml

COMPOSE = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))
SERVICES = COMPOSE["services"]
SETUP_ONLY = {"ollama-pull"}  # one-shot model download, `setup` profile, never part of the running lab


def nets(svc: dict) -> set[str]:
    return set(svc.get("networks", []))  # works for the list form and the mapping form


def test_published_ports_are_loopback_only():
    for name, svc in SERVICES.items():
        for port in svc.get("ports", []):
            assert str(port).startswith("127.0.0.1:"), f"{name} publishes {port!r} beyond loopback"


def test_only_the_three_ui_services_publish_ports():
    assert {n for n, s in SERVICES.items() if s.get("ports")} == {"hmi", "cmms", "scoreboard"}


def test_lab_network_is_internal_and_every_lab_service_is_on_it():
    assert COMPOSE["networks"]["plant"].get("internal") is True
    for name, svc in SERVICES.items():
        if name not in SETUP_ONLY:
            assert "plant" in nets(svc), f"{name} is not on the internal plant network"


def test_only_ui_services_touch_the_internet_facing_network():
    on_edge = {n for n, s in SERVICES.items() if "edge" in nets(s)}
    assert on_edge == {"hmi", "cmms", "scoreboard"} | SETUP_ONLY


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


def test_make_reset_keeps_the_downloaded_model():
    """`down -v` would delete the 4.7 GB model volume; reset removes an explicit allowlist instead,
    which must cover every other named volume (or a new one would silently survive resets)."""
    lines = Path("Makefile").read_text(encoding="utf-8").splitlines()
    recipes = [line for line in lines if line.startswith("\t")]  # commands, not comments
    assert not any("down -v" in r or "down --volumes" in r for r in recipes)
    allowlist = next(line for line in lines if line.startswith("LAB_STATE_VOLUMES"))
    assert set(allowlist.split("=", 1)[1].split()) == set(COMPOSE["volumes"]) - {"ollama-models"}


def test_litellm_never_fetches_catalogs_on_its_own():
    """The agent must not reach outside the lab (CLAUDE.md hard rule): LiteLLM's self-initiated
    downloads are disabled before it can be imported."""
    import agent_operator.llm  # noqa: F401

    assert os.environ["LITELLM_OFFLINE_MODE"] == "true"


def test_no_privileged_containers_or_docker_socket():
    for name, svc in SERVICES.items():
        assert not svc.get("privileged"), f"{name} is privileged"
        assert "docker.sock" not in str(svc.get("volumes", [])), f"{name} mounts the Docker socket"
