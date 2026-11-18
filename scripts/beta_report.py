"""Summarise the beta from every `beta-feedback` issue (the .github/ISSUE_TEMPLATE/beta_feedback.yml form).

    uv run python scripts/beta_report.py                       # pulls the issues with gh, prints Markdown
    uv run python scripts/beta_report.py --out beta-report.md
    uv run python scripts/beta_report.py --from issues.json    # offline, from:
        gh issue list --repo jxbani/DVAP --label beta-feedback --state all --limit 1000 \\
            --json number,title,body,url,state,createdAt > issues.json

Reports: install success rate (overall, by OS and by LLM mode), median install time, problems by
area, the doctor checks that failed, the words that recur in "What broke?", challenge tried/solved
counts, the rating and the class/CTF answer. Answers are read by the form's own labels and options,
so the form is the single source of truth.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
FORM = yaml.safe_load((ROOT / ".github" / "ISSUE_TEMPLATE" / "beta_feedback.yml").read_text(encoding="utf-8"))
FIELDS = {b["id"]: b["attributes"] for b in FORM["body"] if b["type"] != "markdown"}
REPO = "jxbani/DVAP"
NO_ANSWER = "_No response_"
_COMMON = """a an and are as at be but by can could did didn't do does don't for from had has have i i'm in into
is it it's its my no not of on or so that the then there this to too was wasn't we were when which while with would
you your after before because just also only still got get went see saw ran run"""
STOPWORDS = set(_COMMON.split())  # ignored when counting the words that recur in "What broke?"


def sections(body: str) -> dict[str, str]:
    """The form's answers, by field label (GitHub renders each as `### <label>` then the answer)."""
    out: dict[str, str] = {}
    for part in re.split(r"^### ", body or "", flags=re.MULTILINE)[1:]:
        label, _, answer = part.partition("\n")
        answer = answer.strip()
        out[label.strip()] = "" if answer == NO_ANSWER else answer
    return out


def answer(s: dict[str, str], field: str) -> str:
    return s.get(FIELDS[field]["label"], "")


def checked(s: dict[str, str], field: str) -> set[str]:
    return set(re.findall(r"^- \[[xX]\] (.+)$", answer(s, field), re.MULTILINE))


def chosen(s: dict[str, str], field: str) -> list[str]:
    """A multi-select dropdown's answers. Options may contain commas, so match the known ones."""
    text = answer(s, field)
    return [o for o in FIELDS[field]["options"] if o in text]


def minutes(text: str) -> float | None:
    """'12', '12 min', '~15', '1.5 h', '1h' -> minutes; None if there is no number."""
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*(h|hr|hour)?", text.lower())
    if not m:
        return None
    value = float(m.group(1).replace(",", "."))
    return value * 60 if m.group(2) else value


def parse(issue: dict) -> dict:
    s = sections(issue.get("body", ""))
    doctor = answer(s, "doctor").replace("```shell", "").replace("```", "")
    rating = re.match(r"\d", answer(s, "rating"))
    return {
        "number": issue.get("number"), "url": issue.get("url", ""),
        "os": answer(s, "os"), "arch": answer(s, "arch"), "mode": answer(s, "mode"),
        "install": answer(s, "install-result"), "minutes": minutes(answer(s, "install-minutes")),
        "doctor_problems": [f"{st} {name.strip()}" for st, name in
                            re.findall(r"^(FAIL|WARN)\s+(.+?)(?:\s{2,}|$)", doctor, re.MULTILINE)],
        "tried": checked(s, "tried"), "solved": checked(s, "solved"),
        "areas": [a for a in chosen(s, "areas") if a != "None"],
        "broke": [line.strip(" -*\t") for line in answer(s, "broke").splitlines() if line.strip(" -*\t")],
        "confusing": answer(s, "confusing"),
        "rating": int(rating.group()) if rating else None, "use": answer(s, "use"),
    }


def worked(r: dict) -> bool:
    return r["install"].startswith("Yes")


def pct(n: int, d: int) -> str:
    return f"{n}/{d} ({100 * n / d:.0f}%)" if d else "n/a"


def table(rows: list[tuple], head: tuple) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    return out + ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]


def summarise(reports: list[dict]) -> str:
    n = len(reports)
    lines = [f"# DVAP beta report: {n} tester report(s)", ""]
    if not n:
        return "\n".join(lines + ["No beta-feedback issues yet."]) + "\n"

    # install
    answered = [r for r in reports if r["install"]]
    first = sum(r["install"].startswith("Yes, first") for r in answered)
    times = [r["minutes"] for r in reports if r["minutes"] is not None]
    lines += ["## Install", "",
              (f"- **Success rate:** {pct(sum(worked(r) for r in answered), len(answered))} "
               f"(first time without help: {pct(first, len(answered))})"),
              (f"- **Median install time:** {statistics.median(times):.0f} min "
               f"(range {min(times):.0f}–{max(times):.0f}, {len(times)} answers)") if times else
              "- **Median install time:** no answers", ""]
    for key, title in (("os", "OS"), ("arch", "CPU"), ("mode", "LLM mode")):
        groups = Counter(r[key] or "?" for r in reports)
        lines += table([(g, c, pct(sum(worked(r) for r in reports if (r[key] or "?") == g), c))
                        for g, c in groups.most_common()], (title, "reports", "install worked")) + [""]

    # problems
    areas = Counter(a for r in reports for a in r["areas"])
    lines += ["## Problems by area", ""]
    lines += table(areas.most_common(), ("area", "reports")) if areas else ["No areas reported."]
    doctor = Counter(p for r in reports for p in set(r["doctor_problems"]))
    lines += ["", "## Most-reported problems", "", "**`./dvap doctor` checks that failed or warned:**", ""]
    lines += table(doctor.most_common(), ("check", "reports")) if doctor else ["None."]
    words = Counter(w for r in reports for w in {
        w for line in r["broke"] for w in re.findall(r"[a-z][a-z0-9_./-]{2,}", line.lower())} - STOPWORDS)
    recurring = [(w, c) for w, c in words.most_common(15) if c >= 2]
    lines += ["", "**Words that recur in \"What broke?\"** (in 2+ reports):", ""]
    lines += table(recurring, ("word", "reports")) if recurring else ["None yet."]
    lines += ["", "**Everything reported as broken:**", ""]
    lines += [f"- #{r['number']}: {line[:160]}" for r in reports for line in r["broke"]] or ["Nothing."]

    # challenges and verdict
    tried = [o["label"] for o in FIELDS["tried"]["options"]]
    solved = [o["label"] for o in FIELDS["solved"]["options"]]
    count = lambda key, label: sum(label in r[key] for r in reports)
    lines += ["", "## Challenges", ""]
    lines += table([(c, count("tried", c), count("solved", c)) for c in tried if c in solved],
                   ("challenge", "tried", "solved"))
    lines += [""] + [f"- **{c}:** tried by {count('tried', c)}" for c in tried if c not in solved]
    lines += [f"- **{c}:** {count('solved', c)}" for c in solved if c not in tried]
    ratings = [r["rating"] for r in reports if r["rating"]]
    use = Counter(r["use"] for r in reports if r["use"])
    lines += ["", "## Verdict", "",
              f"- **Rating:** {statistics.mean(ratings):.1f} / 5 from {len(ratings)} report(s); "
              + ", ".join(f"{k}★ ×{ratings.count(k)}" for k in range(5, 0, -1) if ratings.count(k))
              if ratings else "- **Rating:** none",
              "- **Would use it in a class or CTF:** " + (", ".join(f"{k} ×{v}" for k, v in use.most_common()) or "none")]
    return "\n".join(lines) + "\n"


def fetch() -> list[dict]:
    out = subprocess.run(["gh", "issue", "list", "--repo", REPO, "--label", "beta-feedback", "--state", "all",
                          "--limit", "1000", "--json", "number,title,body,url,state,createdAt"],
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return json.loads(out.stdout)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--from", dest="source", type=Path, help="read issues from a `gh issue list --json` file")
    p.add_argument("--out", type=Path, help="write the report here instead of printing it")
    args = p.parse_args()
    issues = json.loads(args.source.read_text(encoding="utf-8")) if args.source else fetch()
    report = summarise([parse(i) for i in issues])
    if args.out:
        args.out.write_text(report, encoding="utf-8")
        print(f"wrote {args.out} ({len(issues)} reports)")
    else:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # "★", "–" on Windows consoles
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
