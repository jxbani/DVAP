"""The docs site and README stay in step with the challenges and the project's claims."""

import re
from pathlib import Path

import scripts.check_links as linkcheck
import scripts.gen_docs as gen

README = Path("README.md").read_text(encoding="utf-8")

def test_generated_challenge_pages_and_readme_table_are_current():
    stale = [p.relative_to(gen.ROOT).as_posix() for p, text in gen.render().items()
             if not p.exists() or p.read_text(encoding="utf-8") != text]
    assert not stale, f"run `uv run python scripts/gen_docs.py`: stale {stale}"

def test_every_challenge_is_in_the_site_nav_and_every_asi_is_covered():
    nav = Path("mkdocs.yml").read_text(encoding="utf-8")
    ids = {c["id"] for c in gen.load()}
    assert all(f"challenges/{cid}.md" in nav for cid in ids)
    assert {c["owasp_asi"] for c in gen.load()} == {f"ASI{n:02d}" for n in range(1, 11)}

def test_challenge_pages_have_no_spoilers():
    """Hints collapsed; the solution text and the mitigation only on the separate solution page."""
    for c in gen.load():
        page = (gen.OUT / f"{c['id']}.md").read_text(encoding="utf-8")
        assert page.count('??? tip "Hint') == len(c["hints"])  # collapsed by default
        assert c["mitigation"].strip().splitlines()[0] not in page
        solution = (gen.ROOT / "challenges" / c["id"] / "solution.md").read_text(encoding="utf-8")
        first_step = next(line for line in solution.splitlines()[1:] if line.strip())
        assert first_step not in page
        assert '!!! warning "Spoilers"' in (gen.OUT / "solutions" / f"{c['id']}.md").read_text(encoding="utf-8")

def test_readme_has_the_required_parts_and_no_official_owasp_claim():
    for badge in ("actions/workflows/ci.yml/badge.svg", "img.shields.io/github/v/release",
                  "license", "api.scorecard.dev"):
        assert badge in README
    assert "mapped to the OWASP Top 10 for Agentic Applications" in README
    assert "never connect it to real industrial equipment" in README
    assert re.search(r"not\*\* an official OWASP project", README)
    assert not re.search(r"(?<!not )(?<!not\*\* )an official OWASP project", README)
    assert "![DVAP demo" in README and "```bash" in README

def test_security_scope():
    security = Path("SECURITY.md").read_text(encoding="utf-8")
    assert "## Out of scope: the intentional vulnerabilities" in security
    for term in ("Host impact", "Sandbox escape", "Unintended network exposure"):
        assert term in security
    assert "security/advisories/new" in security  # GitHub private vulnerability reporting

def test_site_includes_resolve():
    """docs/security.md and docs/contributing.md include root files, whose links must be absolute."""
    for name in ("SECURITY.md", "CONTRIBUTING.md"):
        links = re.findall(r"\]\(([^)]+)\)", Path(name).read_text(encoding="utf-8"))
        assert all(link.startswith(("https://", "#", "mailto:")) for link in links), (name, links)
    cfg = Path("mkdocs.yml").read_text(encoding="utf-8")
    assert "pymdownx.snippets" in cfg


def test_link_checker_resolves_local_files_and_docs_pages_without_network(tmp_path):
    site = tmp_path / "site"
    (site / "challenges" / "C01").mkdir(parents=True)
    (site / "challenges" / "C01" / "index.html").write_text("")
    (tmp_path / "LICENSE").write_text("")
    md = tmp_path / "README.md"
    md.write_text(f"[a](LICENSE) [b]({linkcheck.DOCS_URL}challenges/C01/) [c]({linkcheck.DOCS_URL}nope/) "
                  "[d](missing.md#x) [e](http://127.0.0.1:8080)")
    assert linkcheck.check(md, site) == [f"{linkcheck.DOCS_URL}nope/", "missing.md#x"]


def test_demo_media_exist_and_are_used():
    """Recorded by scripts/record_demo.py (see docs/RELEASING.md); the placeholder is gone."""
    import struct

    assets = Path("docs/assets")
    for doc, prefix in ((README, "docs/assets/"), (Path("docs/index.md").read_text(encoding="utf-8"), "assets/")):
        assert f"]({prefix}demo.gif)" in doc and f"]({prefix}demo-full.mp4)" in doc
        assert "TODO" not in doc and "placeholder" not in doc
    assert (assets / "demo.gif").stat().st_size < 5_000_000  # README embeds it: keep it light
    assert (assets / "demo-full.mp4").read_bytes()[4:8] == b"ftyp"  # an MP4 container
    png = (assets / "social-preview.png").read_bytes()
    assert struct.unpack(">II", png[16:24]) == (1280, 640)  # GitHub's social preview size
