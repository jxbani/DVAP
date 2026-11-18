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
import scripts.release_version as rv
from bench import ops

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
    assert re.search(r"^dvap \d+\.\d+\.\d+(-(alpha|beta|rc)\.\d+)?$", out.stdout, re.MULTILINE)  # .env.example
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
    changelog.write_text("## [0.9.0-beta.10] - 2026-02-01\n\n- ten\n\n## [0.9.0-beta.1] - 2026-01-01\n\n- one\n\n"
                         "[Unreleased]: https://x/compare\n[0.9.0-beta.1]: https://x/tag\n")
    out = subprocess.run(["bash", "-c", awk], cwd=tmp_path, env={"VERSION": "0.9.0-beta.1", "PATH": "/usr/bin:/bin"},
                         capture_output=True, text=True, check=False)
    assert out.stdout.strip() == "- one"  # beta.1, not beta.10; and the last section stops at the link definitions


def test_versions_agree_like_the_release_workflow_checks():
    """The repo is ready to tag: the release workflow's verify job, run on the current version."""
    version = ops.project_version()
    assert rv.check(f"v{version}") == (version, [])


@pytest.mark.parametrize(("semver", "pep440", "pre"), [
    ("0.9.0", "0.9.0", False), ("0.9.0-alpha.2", "0.9.0a2", True), ("0.9.0-beta.1", "0.9.0b1", True),
    ("1.0.0-rc.10", "1.0.0rc10", True), ("10.20.30", "10.20.30", False),
])
def test_semver_maps_to_pep440_explicitly(semver, pep440, pre):
    assert rv.pep440(semver) == pep440 and rv.is_prerelease(semver) == pre


@pytest.mark.parametrize("bad", ["0.9", "v0.9.0", "0.9.0-preview.1", "0.9.0-beta", "0.9.0-beta.01", "01.0.0",
                                 "0.9.0b1", "0.9.0-beta.1+build.5"])
def test_versions_outside_the_rules_are_refused(bad):
    """Packaging would rewrite some of these silently ("-preview.1" becomes rc1), so a release refuses them."""
    with pytest.raises(ValueError):
        rv.parse(bad)


def test_the_verify_job_names_every_disagreement(tmp_path):
    for name in ("pyproject.toml", ".env.example", "CHANGELOG.md"):
        (tmp_path / name).write_text(Path(name).read_text(encoding="utf-8"), encoding="utf-8")
    errors = rv.check("v9.9.9-rc.9", tmp_path)[1]  # a new tag, nothing else bumped
    assert [e.split(" ")[0] for e in errors] == ["pyproject.toml", ".env.example", "CHANGELOG.md"]
    assert "'9.9.9rc9' (PEP 440)" in errors[0]
    assert rv.check("9.9.9", tmp_path)[1] == ["tag '9.9.9' must start with v"]


def tag_filter_matches(pattern: str, tag: str) -> bool:
    """GitHub's filter-pattern syntax, as far as release.yml uses it: [0-9], + (one or more), * (not /)."""
    regex = re.escape(pattern).replace(re.escape("[0-9]"), "[0-9]").replace(re.escape("+"), "+")
    return re.fullmatch(regex.replace(re.escape("*"), "[^/]*"), tag) is not None


def test_release_triggers_on_stable_and_prerelease_tags():
    tags = yaml.safe_load(Path(".github/workflows/release.yml").read_text(encoding="utf-8"))[True]["push"]["tags"]
    for tag in ("v0.1.0", "v0.9.0-beta.1", "v1.0.0-rc.1", "v10.20.30"):
        assert any(tag_filter_matches(p, tag) for p in tags), tag
    for tag in ("0.9.0", "v0.9", "release-1"):
        assert not any(tag_filter_matches(p, tag) for p in tags), tag


def test_prereleases_are_never_latest_and_images_carry_only_their_version():
    jobs = yaml.safe_load(Path(".github/workflows/release.yml").read_text(encoding="utf-8"))["jobs"]
    build = next(s for s in jobs["images"]["steps"] if s.get("id") == "build")
    assert build["with"]["tags"] == "${{ env.IMAGE }}:${{ env.VERSION }}"  # no latest, no stable
    create = next(s for s in jobs["release"]["steps"] if s.get("name") == "Create the release")["run"]
    assert 'if [ "$PRERELEASE" = true ]; then kind=(--prerelease --latest=false); else kind=(--latest); fi' in create
    assert '"${kind[@]}"' in create
    assert jobs["release"]["env"]["PRERELEASE"] == "${{ needs.verify.outputs.prerelease }}"
    assert jobs["verify"]["outputs"]["prerelease"] == "${{ steps.v.outputs.prerelease }}"


def test_make_dist_refuses_a_version_the_zip_would_not_pull():
    dist.check_version(ops.project_version())
    for bad in ("0.9.0-preview.1", "99.0.0"):
        with pytest.raises(ValueError):
            dist.check_version(bad)


FRESH = Path("scripts/verify_fresh_install.sh")


def test_fresh_install_workflow_runs_the_script_after_each_release():
    wf = yaml.safe_load(Path(".github/workflows/fresh-install.yml").read_text(encoding="utf-8"))
    release_name = yaml.safe_load(Path(".github/workflows/release.yml").read_text(encoding="utf-8"))["name"]
    assert wf[True]["workflow_run"]["workflows"] == [release_name]  # yaml reads the `on:` key as True
    assert wf["env"]["BUDGET_SECONDS"] == "900"  # the 15-minute promise
    for name, job in wf["jobs"].items():
        assert any(FRESH.as_posix() in s.get("run", "") for s in job["steps"]), name


@pytest.mark.skipif(sys.platform == "win32", reason="runs the script with bash, as on the runners")
def test_fresh_install_script_without_docker_checks_the_zip_cli(tmp_path):
    """The macos-latest path: unzip the release, run the CLI, and doctor must FAIL on Docker."""
    fake = tmp_path / "bin"
    fake.mkdir()
    (fake / "docker").write_text("#!/bin/sh\necho 'Cannot connect to the Docker daemon' >&2\nexit 1\n")
    (fake / "docker").chmod(0o755)
    env = {"PATH": f"{fake}:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "NO_DOCKER": "1",
           "DVAP_ZIP": str(dist.build("9.9.9", tmp_path)), "WORK_DIR": str(tmp_path / "work")}
    out = subprocess.run(["bash", str(FRESH.resolve())], env=env, capture_output=True, text=True, check=False)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "FAIL  Docker" in out.stdout and "OK: the release CLI runs here" in out.stdout
