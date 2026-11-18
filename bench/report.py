"""Turns a benchmark result dict into results/<stamp>/{results.json, results.csv, report.html} plus
a prompts/ folder, and regenerates the results section of docs/BENCHMARK.md from the latest run."""

import csv
import json
import statistics
from pathlib import Path
from typing import Any

HMI_CHART = Path("services/hmi/hmi/static/vendor/chart.umd.min.js")
README = Path("docs/BENCHMARK.md")  # the results section lives on the docs page
BENCH_START, BENCH_END = "<!-- BENCH:START -->", "<!-- BENCH:END -->"
CSV_FIELDS = ["model", "challenge", "asi", "title", "success_rate", "mean_tool_calls",
              "mean_tokens", "mean_time_to_incident_s", "block_rate"]


def _asi_summary(data: dict) -> list[dict]:
    """Mean success rate per OWASP ASI category per model."""
    rows = []
    models = data["config"]["models"]
    by_asi: dict[str, dict[str, list[float]]] = {}
    for r in data["results"]:
        by_asi.setdefault(r["asi"], {}).setdefault(r["model"], []).append(r["success_rate"])
    for asi in sorted(by_asi):
        row: dict[str, Any] = {"asi": asi}
        for m in models:
            vals = by_asi[asi].get(m, [])
            row[m] = round(statistics.fmean(vals), 3) if vals else None
        rows.append(row)
    return rows


def write_run(data: dict, stamp: str, root: str = "results", update_readme: bool = True) -> Path:
    out = Path(root) / stamp
    (out / "prompts").mkdir(parents=True, exist_ok=True)

    (out / "results.json").write_text(json.dumps(data, indent=2), encoding="utf-8")

    with (out / "results.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for r in data["results"]:
            w.writerow({k: r.get(k) for k in CSV_FIELDS})

    prompts = data["prompts"]
    (out / "prompts" / "system_prompt.txt").write_text(prompts["system_prompt"], encoding="utf-8")
    for cid, text in prompts["attacks"].items():
        body = f"objective: {prompts['objectives'].get(cid, '')}\n\nattack vector:\n{text}\n"
        (out / "prompts" / f"{cid}.txt").write_text(body, encoding="utf-8")
    (out / "prompts" / "benign_workload.txt").write_text(prompts["benign_workload"], encoding="utf-8")

    (out / "report.html").write_text(_html(data, stamp), encoding="utf-8")
    if update_readme:
        _update_readme(data, stamp)
    return out


def _html(data: dict, stamp: str) -> str:
    chart_js = HMI_CHART.read_text(encoding="utf-8") if HMI_CHART.exists() else ""
    chart_tag = (f"<script>{chart_js}</script>" if chart_js
                 else '<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>')
    payload = json.dumps({"data": data, "asi": _asi_summary(data)}).replace("</", "<\\/")
    cfg = data["config"]
    benign = data["benign"]
    benign_line = (f"Benign workload: {benign['false_positives']}/{benign['decisions']} decisions denied "
                   f"(false-positive rate {benign['fp_rate']:.1%}).") if benign else "Guard off (no benign check)."
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>DVAP benchmark {stamp}</title>
<style>
  :root {{ color-scheme: light dark; --line: #8884; }}
  body {{ font: 15px/1.5 system-ui, sans-serif; margin: 0; padding: 24px; max-width: 1100px; }}
  h1 {{ font-size: 22px; }} h2 {{ font-size: 17px; margin-top: 32px; }}
  .meta {{ color: #888; font-size: 13px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }}
  th, td {{ border: 1px solid var(--line); padding: 6px 9px; text-align: left; }}
  th {{ background: #8881; }} td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .chart {{ position: relative; height: 340px; margin: 12px 0 8px; }}
  .sim {{ background: #f2a93b; color: #1a1204; border-radius: 4px; padding: 1px 6px; font-size: 12px; }}
</style></head>
<body>
  <h1>DVAP benchmark <span class="sim">SIMULATION</span></h1>
  <p class="meta">Generated {data['generated_at']} · guard <b>{cfg['guard']}</b> · {cfg['runs']} run(s)/challenge ·
     seeds {cfg['seeds']} · models: {', '.join(cfg['models'])}</p>
  <p>{benign_line}</p>

  <h2>Attack success rate by challenge</h2>
  <div class="chart"><canvas id="success"></canvas></div>
  <div id="block-wrap" hidden><h2>Guard block rate by challenge</h2><div class="chart"><canvas id="block"></canvas></div></div>

  <h2>Summary by OWASP ASI category</h2>
  <table id="asi"><thead></thead><tbody></tbody></table>

  <h2>Detail</h2>
  <table id="detail"><thead></thead><tbody></tbody></table>

{chart_tag}
<script>
const PAYLOAD = {payload};
const data = PAYLOAD.data, models = data.config.models, guardOn = data.config.guard === "on";
const challenges = [...new Set(data.results.map(r => r.challenge))];
const COLORS = ["#4f8cff","#ff6b6b","#3ebd8f","#f2a93b","#a66bff","#00b4d8"];
const cell = (v) => v === null || v === undefined ? "—" : v;

function series(field) {{
  return models.map((m, i) => ({{
    label: m,
    backgroundColor: COLORS[i % COLORS.length],
    data: challenges.map(c => {{
      const r = data.results.find(x => x.model === m && x.challenge === c);
      return r ? r[field] : null;
    }}),
  }}));
}}
function bar(id, field) {{
  new Chart(document.getElementById(id), {{
    type: "bar",
    data: {{ labels: challenges, datasets: series(field) }},
    options: {{ animation: false, responsive: true, maintainAspectRatio: false,
      scales: {{ y: {{ beginAtZero: true, max: 1, title: {{ display: true, text: field }} }} }} }},
  }});
}}
bar("success", "success_rate");
if (guardOn) {{ document.getElementById("block-wrap").hidden = false; bar("block", "block_rate"); }}

function table(id, headers, rows) {{
  const t = document.getElementById(id);
  t.tHead.innerHTML = "<tr>" + headers.map(h => `<th>${{h}}</th>`).join("") + "</tr>";
  t.tBodies[0].innerHTML = rows.map(cols =>
    "<tr>" + cols.map((c, i) => i === 0 ? `<td>${{c}}</td>` : `<td class="num">${{cell(c)}}</td>`).join("") + "</tr>"
  ).join("");
}}
table("asi", ["OWASP ASI", ...models], PAYLOAD.asi.map(r => [r.asi, ...models.map(m => r[m])]));
table("detail",
  ["Model", "Challenge", "ASI", "Success", "Mean tool calls", "Mean tokens", "Mean TTI (s)", "Block rate"],
  data.results.map(r => [r.model, r.challenge + " " + r.title, r.asi, r.success_rate,
    r.mean_tool_calls, r.mean_tokens, r.mean_time_to_incident_s, r.block_rate]));
</script>
</body></html>
"""


def _markdown_table(data: dict) -> str:
    models = data["config"]["models"]
    challenges = [r["challenge"] for r in data["results"] if r["model"] == models[0]]
    header = "| Challenge | ASI | " + " | ".join(models) + " |"
    sep = "|" + "---|" * (len(models) + 2)
    lines = [header, sep]
    for c in challenges:
        asi = next(r["asi"] for r in data["results"] if r["challenge"] == c)
        cells = []
        for m in models:
            r = next((x for x in data["results"] if x["model"] == m and x["challenge"] == c), None)
            cells.append(f"{r['success_rate']:.0%}" if r else "—")
        lines.append(f"| {c} | {asi} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _update_readme(data: dict, stamp: str) -> None:
    cfg = data["config"]
    benign = data["benign"]
    benign_line = (f"- Benign false-positive rate (guard on): **{benign['fp_rate']:.1%}** "
                   f"({benign['false_positives']}/{benign['decisions']} decisions)\n") if benign else ""
    section = (
        f"{BENCH_START}\n"
        "## Benchmark results\n\n"
        f"_Generated {data['generated_at']} from run `{stamp}` — guard **{cfg['guard']}**, "
        f"{cfg['runs']} run(s)/challenge, seeds {cfg['seeds']}._\n\n"
        f"Models: {', '.join(f'`{m}`' for m in cfg['models'])}.\n\n"
        "Attack success rate (higher = the model fell for the attack more often):\n\n"
        f"{_markdown_table(data)}\n\n"
        f"{benign_line}"
        f"\nFull report (local, git-ignored — regenerate with `make bench`): "
        f"`results/{stamp}/report.html` · data: `results/{stamp}/results.json`.\n"
        f"{BENCH_END}"
    )
    if README.exists():
        text = README.read_text(encoding="utf-8")
        if BENCH_START in text and BENCH_END in text:
            pre = text[: text.index(BENCH_START)]
            post = text[text.index(BENCH_END) + len(BENCH_END):]
            README.write_text(pre + section + post, encoding="utf-8")
            return
        README.write_text(text.rstrip() + "\n\n" + section + "\n", encoding="utf-8")
        return
    README.write_text(
        "# DVAP — Damn Vulnerable Agentic Plant\n\n"
        "An intentionally vulnerable, fully simulated agentic ICS lab for the OWASP Top 10 for "
        "Agentic Applications. See [CLAUDE.md](CLAUDE.md) and [docs/](docs/).\n\n"
        f"{section}\n",
        encoding="utf-8",
    )
