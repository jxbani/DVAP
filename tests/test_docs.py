"""The docs site and README stay in step with the challenges and the project's claims."""

import re
from pathlib import Path

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
