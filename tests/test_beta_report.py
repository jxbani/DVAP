"""scripts/beta_report.py reads beta-feedback issues as GitHub renders the issue form."""

import scripts.beta_report as br

DOCTOR_OK = "PASS  Docker             Engine 28.1.1 (need 24.0+)\n\nAll checks passed. Next: ./dvap up"
DOCTOR_MEM = ("PASS  Docker             Engine 28.1.1 (need 24.0+)\n"
              "FAIL  Memory for Docker  3.8 GB (need 4 GB for replay mode)\n"
              "                         fix: Give WSL at least 4 GB\n"
              "WARN  Repository on /mnt  slow file access\n\n1 check(s) failed.")


def render(**answers) -> str:
    """An issue body the way GitHub renders this form: `### <label>`, then the answer."""
    out = []
    for fid, attrs in br.FIELDS.items():
        value = answers.get(fid.replace("-", "_"))
        if attrs.get("options") and isinstance(attrs["options"][0], dict):  # checkboxes
            text = "\n".join(f"- [{'X' if o['label'] in (value or ()) else ' '}] {o['label']}" for o in attrs["options"])
        elif fid == "doctor" and value:
            text = f"```shell\n{value}\n```"
        elif isinstance(value, list):
            text = ", ".join(value)
        else:
            text = value or br.NO_ANSWER
        out.append(f"### {attrs['label']}\n\n{text}")
    return "\n\n".join(out)


ISSUES = [
    {"number": 1, "url": "u1", "body": render(
        os="Linux", arch="x86_64 / amd64 (Intel, AMD)", mode="replay", install_result="Yes, first time",
        install_minutes="12", doctor=DOCTOR_OK, tried=["C01", "C02", "C05"], solved=["C01", "C02"],
        areas=["None"], rating="5 - excellent", use="Yes, both")},
    {"number": 2, "url": "u2", "body": render(
        os="Windows (WSL2)", arch="x86_64 / amd64 (Intel, AMD)", mode="ollama",
        install_result="Yes, after fixing something (please say what below)", install_minutes="~25 min",
        doctor=DOCTOR_MEM, tried=["C01", "C03"], solved=["C01"],
        areas=["Install / Docker", "Challenges (story, hints, checker)"],
        broke="- The ollama model download stalled at 80%\n- C03 checker never fired",
        rating="3 - okay", use="Maybe")},
    {"number": 3, "url": "u3", "body": render(
        os="macOS", arch="arm64 / aarch64 (Apple Silicon, ARM)", mode="replay", install_result="No",
        install_minutes="1.5 h", doctor=DOCTOR_MEM, tried=["C01"], areas=["Install / Docker", "Docs"],
        broke="ollama download failed twice", rating="2 - poor", use="No")},
]


def test_answers_are_read_by_the_forms_labels():
    r = br.parse(ISSUES[1])
    assert (r["os"], r["mode"], r["minutes"], r["rating"]) == ("Windows (WSL2)", "ollama", 25.0, 3)
    assert r["tried"] == {"C01", "C03"} and r["solved"] == {"C01"}
    assert r["areas"] == ["Install / Docker", "Challenges (story, hints, checker)"]  # commas inside an option
    assert r["doctor_problems"] == ["FAIL Memory for Docker", "WARN Repository on /mnt"]
    assert r["broke"] == ["The ollama model download stalled at 80%", "C03 checker never fired"]
    empty = br.parse({"number": 9, "body": render()})
    assert empty["minutes"] is None and empty["areas"] == [] and empty["broke"] == [] and empty["rating"] is None


def test_minutes_understands_how_people_write_durations():
    assert [br.minutes(t) for t in ("12", "~15 min", "1.5 h", "1h", "90", "about 2 hours", "", "quick")] == \
        [12, 15, 90, 60, 90, 120, None, None]


def test_summary_has_the_beta_numbers():
    report = br.summarise([br.parse(i) for i in ISSUES])
    assert "**Success rate:** 2/3 (67%) (first time without help: 1/3 (33%))" in report
    assert "**Median install time:** 25 min (range 12–90, 3 answers)" in report
    assert "| Install / Docker | 2 |" in report and "| Docs | 1 |" in report and "| None |" not in report
    assert "| FAIL Memory for Docker | 2 |" in report
    assert "| ollama | 2 |" in report and "| download | 2 |" in report  # recurring words, per report
    assert "| C01 | 3 | 2 |" in report and "| C03 | 1 | 0 |" in report
    assert "- **./dvap demo:** tried by 0" in report and "| ./dvap demo |" not in report
    assert "- **Got around SafeEnvelope in a defended variant:** 0" in report
    assert "**Rating:** 3.3 / 5 from 3 report(s)" in report
    assert "- #2: C03 checker never fired" in report


def test_no_reports_yet():
    assert "No beta-feedback issues yet." in br.summarise([])
