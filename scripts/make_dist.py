"""Build dist/dvap-<version>.zip: everything needed to run DVAP from the published images,
without cloning (the release workflow attaches it to the GitHub Release).

    python3 scripts/make_dist.py 1.0.0

The version is DVAP's SemVer version (pre-releases too), and must be .env.example's DVAP_VERSION:
the zip's .env.example decides which images it pulls.
"""

import re
import sys
import zipfile
from pathlib import Path

if __package__ in (None, ""):  # run as a script: make scripts.release_version importable
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scripts.release_version import parse

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    "dvap", "dvap.ps1", "docker-compose.yml", "docker-compose.api.yml", ".env.example",
    "gateway/nginx.conf",  # mounted by the gateway service
    "bench/__init__.py", "bench/__main__.py", "bench/cli.py", "bench/ops.py", "bench/doctor.py", "bench/stage.py",
    "README.md", "LICENSE", "CHANGELOG.md",
]
EXECUTABLE = {"dvap"}


def contents() -> list[str]:
    challenges = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "challenges").rglob("*") if p.is_file())
    return FILES + challenges  # the scoreboard mounts ./challenges


def build(version: str, out: Path = ROOT / "dist") -> Path:
    out.mkdir(exist_ok=True)
    target = out / f"dvap-{version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for rel in contents():
            info = zipfile.ZipInfo(f"dvap-{version}/{rel}", date_time=(2020, 1, 1, 0, 0, 0))  # reproducible
            info.external_attr = (0o755 if rel in EXECUTABLE else 0o644) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (ROOT / rel).read_bytes())
    return target


def check_version(version: str) -> None:
    parse(version)  # ValueError unless X.Y.Z or X.Y.Z-(alpha|beta|rc).N
    env = re.search(r"^DVAP_VERSION=(.*)$", (ROOT / ".env.example").read_text(encoding="utf-8"), re.MULTILINE)
    if not env or env.group(1).strip() != version:
        raise ValueError(f".env.example has DVAP_VERSION={env.group(1) if env else None}, not {version}: "
                         "the zip would pull other images")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        check_version(sys.argv[1])
    except ValueError as e:
        sys.exit(f"make_dist: {e}")
    print(build(sys.argv[1]))
