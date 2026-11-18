"""Build dist/dvap-<version>.zip: everything needed to run DVAP from the published images,
without cloning (the release workflow attaches it to the GitHub Release).

    python3 scripts/make_dist.py 0.1.0
"""

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    "dvap", "dvap.ps1", "docker-compose.yml", "docker-compose.api.yml", ".env.example",
    "gateway/nginx.conf",  # mounted by the gateway service
    "bench/__init__.py", "bench/__main__.py", "bench/cli.py", "bench/ops.py", "bench/doctor.py",
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


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(build(sys.argv[1]))
