"""DVAP's version rules, in one place (standard library only: the release workflow runs it bare).

DVAP is versioned with SemVer: the git tag (v0.9.0-beta.1), .env.example's DVAP_VERSION (the image
tag), the CHANGELOG heading and the release zip all use it. pyproject.toml must use PEP 440 instead:
Python packaging rewrites "0.9.0-beta.1" to "0.9.0b1" anyway (uv.lock and built metadata show
that), and turns labels it doesn't know into something else ("-preview.1" silently becomes rc1).
So the mapping is explicit, and only these pre-release labels are allowed:

    SemVer            PEP 440 (pyproject.toml)
    1.2.3             1.2.3
    1.2.3-alpha.N     1.2.3aN
    1.2.3-beta.N      1.2.3bN
    1.2.3-rc.N        1.2.3rcN

    python3 scripts/release_version.py v0.9.0-beta.1

checks that the tag, pyproject.toml, .env.example and CHANGELOG.md agree, and prints
`version=0.9.0-beta.1` and `prerelease=true` for $GITHUB_OUTPUT (or `::error::` lines, exit 1).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NUM = r"(?:0|[1-9]\d*)"  # SemVer: no leading zeros
SEMVER = re.compile(rf"^({NUM}\.{NUM}\.{NUM})(?:-(alpha|beta|rc)\.({NUM}))?$")
PEP440_LABEL = {"alpha": "a", "beta": "b", "rc": "rc"}


def parse(version: str) -> tuple[str, str | None, str | None]:
    """(core, label, number) of a DVAP SemVer version; ValueError for anything else."""
    m = SEMVER.match(version)
    if not m:
        raise ValueError(f"{version!r} is not a DVAP version: X.Y.Z or X.Y.Z-(alpha|beta|rc).N")
    return m.group(1), m.group(2), m.group(3)


def is_prerelease(version: str) -> bool:
    return parse(version)[1] is not None


def pep440(version: str) -> str:
    core, label, number = parse(version)
    return core if label is None else f"{core}{PEP440_LABEL[label]}{number}"


def check(tag: str, root: Path = ROOT) -> tuple[str, list[str]]:
    """(version, errors) for a release tag against the files in `root`."""
    if not tag.startswith("v"):
        return tag, [f"tag {tag!r} must start with v"]
    version = tag[1:]
    try:
        want_py = pep440(version)
    except ValueError as e:
        return version, [str(e)]
    errors = []
    py = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.MULTILINE)
    if not py or py.group(1) != want_py:
        errors.append(f"pyproject.toml version is {py.group(1) if py else None!r}; for {tag} it must be "
                      f"{want_py!r} (PEP 440)")
    env = re.search(r"^DVAP_VERSION=(.*)$", (root / ".env.example").read_text(encoding="utf-8"), re.MULTILINE)
    if not env or env.group(1).strip() != version:
        errors.append(f".env.example DVAP_VERSION is {env.group(1) if env else None!r}; it must be {version!r}")
    if not re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$",
                     (root / "CHANGELOG.md").read_text(encoding="utf-8"), re.MULTILINE):
        errors.append(f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' section")
    return version, errors


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__)
        return 2
    version, errors = check(argv[0])
    for e in errors:
        print(f"::error::{e}")
    if errors:
        return 1
    print(f"version={version}")
    print(f"prerelease={'true' if is_prerelease(version) else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
