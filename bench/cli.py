"""`dvap` command line. Subcommand: `bench`.

Examples:
  dvap bench --models fake:comply,fake:refuse --runs 1 --guard off
  dvap bench --models ollama/qwen2.5:7b-instruct --runs 5 --guard on
  dvap bench --models anthropic/claude-3-5-sonnet,fake:comply --runs 3 --guard off --challenges C01,C02
"""

import argparse
import asyncio

from bench.lab import now_stamp
from bench.report import write_run
from bench.runner import run_matrix


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="dvap", description="DVAP: Damn Vulnerable Agentic Plant")
    sub = parser.add_subparsers(dest="command", required=True)

    bench = sub.add_parser("bench", help="benchmark models (and the guard) against the challenges")
    bench.add_argument("--models", required=True,
                       help="comma-separated model specs: fake:comply, fake:refuse, ollama/<m>, anthropic/<m>, openai/<m>")
    bench.add_argument("--runs", type=int, default=3, help="runs per challenge (fixed seeds 0..N-1)")
    bench.add_argument("--guard", choices=["on", "off"], default="off", help="SafeEnvelope on or off")
    bench.add_argument("--challenges", default=None, help="comma-separated challenge ids (default: all)")
    bench.add_argument("--out", default="results", help="output root directory")

    args = parser.parse_args(argv)
    if args.command == "bench":
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        challenges = [c.strip() for c in args.challenges.split(",")] if args.challenges else None
        data = asyncio.run(run_matrix(models, args.runs, args.guard == "on", challenges))
        out = write_run(data, now_stamp(), args.out)
        print(f"wrote {out}/results.json, results.csv, report.html and updated README.md")


if __name__ == "__main__":
    main()
