"""Check that every link in a Markdown file resolves (stdlib only).

    python scripts/check_links.py README.md                 # docs-site links fetched live
    python scripts/check_links.py README.md --site site     # docs-site links checked in a local mkdocs build

- relative links: the file must exist (anchors are not checked);
- links into the docs site (DOCS_URL): with --site, the page must exist in that build, so CI
  catches a broken docs link before it is deployed; without it, they are fetched;
- other http(s) links: fetched, following redirects; anything but a 2xx/3xx fails;
- the lab's own http://127.0.0.1 URLs are skipped (they only exist while it runs).
"""

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

DOCS_URL = "https://jxbani.github.io/DVAP/"
LINK = re.compile(r"\]\(([^)\s]+)\)")  # [text](target) and ![alt](target)


def links(markdown: str) -> list[str]:
    return sorted(set(LINK.findall(markdown)))


def site_page(url: str, site: Path) -> Path:
    path = url.removeprefix(DOCS_URL).split("#")[0]
    return site / path / "index.html" if path == "" or path.endswith("/") else site / path


def fetch(url: str) -> str | None:
    """None if the URL answers, else the reason it doesn't."""
    req = urllib.request.Request(url, headers={"User-Agent": "dvap-link-check"})
    for _ in range(2):  # one retry for flaky CDNs
        try:
            with urllib.request.urlopen(req, timeout=20):
                return None
        except urllib.error.HTTPError as e:
            reason = f"HTTP {e.code}"
        except (urllib.error.URLError, OSError) as e:
            reason = str(e)
    return reason


def check(file: Path, site: Path | None) -> list[str]:
    problems = []
    for target in links(file.read_text(encoding="utf-8")):
        if target.startswith(("http://127.0.0.1", "http://localhost", "mailto:", "#")):
            continue
        if site and target.startswith(DOCS_URL):
            page = site_page(target, site)
            reason = None if page.exists() else f"not in the docs build ({page})"
        elif target.startswith(("http://", "https://")):
            reason = fetch(target)
        else:
            path = file.parent / target.split("#")[0]
            reason = None if path.exists() else "no such file"
        print(f"{'ok  ' if reason is None else 'FAIL'}  {target}" + (f"  ({reason})" if reason else ""))
        if reason:
            problems.append(target)
    return problems


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("files", nargs="+", type=Path)
    p.add_argument("--site", type=Path, help="a local mkdocs build to check docs-site links against")
    args = p.parse_args()
    broken = [link for f in args.files for link in check(f, args.site)]
    print(f"\n{len(broken)} broken link(s)." if broken else "\nAll links resolve.")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
