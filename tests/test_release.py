"""The release artefacts: dvap-<version>.zip runs the lab without a clone, and the release
workflow's changelog extraction finds a version's section."""

import re
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import yaml

import scripts.make_dist as dist

COMPOSE = yaml.safe_load(Path("docker-compose.yml").read_text(encoding="utf-8"))


def test_zip_has_everything_compose_mounts_and_an_executable_cli(tmp_path):
    z = zipfile.ZipFile(dist.build("9.9.9", tmp_path))
    names = {n.removeprefix("dvap-9.9.9/") for n in z.namelist()}
    for svc in COMPOSE["services"].values():  # every bind-mounted host path ships in the zip
        for vol in svc.get("volumes", []):
            src = vol.split(":")[0]
            if src.startswith("./"):
                assert any(n == src[2:] or n.startswith(src[2:].rstrip("/") + "/") for n in names), src
    assert {"docker-compose.yml", ".env.example", "dvap", "dvap.ps1", "bench/cli.py"} <= names
    assert "challenges/C01/challenge.yaml" in names
    assert z.getinfo("dvap-9.9.9/dvap").external_attr >> 16 == 0o755
    assert not any(n.startswith(("services/", "tests/", ".git")) or n == ".env" for n in names)


def test_the_unzipped_cli_runs_without_the_source(tmp_path):
    zipfile.ZipFile(dist.build("9.9.9", tmp_path)).extractall(tmp_path)
    root = tmp_path / "dvap-9.9.9"
    out = subprocess.run([sys.executable, "-m", "bench", "version"], cwd=root, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stderr
    assert re.search(r"^dvap \d+\.\d+\.\d+$", out.stdout, re.MULTILINE)  # from .env.example, no pyproject
    out = subprocess.run([sys.executable, "-m", "bench", "update"], cwd=root, capture_output=True, text=True, check=False)
    assert out.returncode == 1 and "release download" in out.stdout


@pytest.mark.skipif(sys.platform == "win32", reason="runs the workflow's awk with bash, as on the Linux runner")
def test_release_notes_extraction_matches_keep_a_changelog(tmp_path):
    awk = next(s["run"] for s in yaml.safe_load(Path(".github/workflows/release.yml").read_text(encoding="utf-8"))
               ["jobs"]["release"]["steps"] if "awk" in s.get("run", "")).splitlines()[0]
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text("# Changelog\n\n## [Unreleased]\n\n- next\n\n## [1.2.0] - 2026-01-02\n\n### Added\n\n"
                         "- thing\n\n## [1.1.0] - 2025-12-01\n\n- old\n\n[1.2.0]: https://x\n")
    awk = awk.replace("CHANGELOG.md > notes.md", str(changelog.name))
    out = subprocess.run(["bash", "-c", awk], cwd=tmp_path, env={"VERSION": "1.2.0", "PATH": "/usr/bin:/bin"},
                         capture_output=True, text=True, check=False)
    assert out.stdout.strip().splitlines() == ["### Added", "", "- thing"], out
    out = subprocess.run(["bash", "-c", awk], cwd=tmp_path, env={"VERSION": "1.2", "PATH": "/usr/bin:/bin"},
                         capture_output=True, text=True, check=False)
    assert out.stdout == ""  # a prefix of another version matches nothing


def test_versions_agree_like_the_release_workflow_checks():
    version = re.search(r'^version = "(.+)"', Path("pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE).group(1)
    assert f"DVAP_VERSION={version}\n" in Path(".env.example").read_text(encoding="utf-8")
