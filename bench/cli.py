"""`dvap` command line: run the lab, check the machine, and benchmark models.

  ./dvap up [--mode replay|ollama|api] [--build]   start the lab (first run: creates .env)
  ./dvap demo                                      a malicious ticket overdoses the chlorine
  ./dvap doctor                                    can this machine run DVAP? (with fixes)
  ./dvap reset [C01]                               wipe lab state (keeps the model), or one challenge
  ./dvap status | logs [service] | down | version | update
  ./dvap bench --models fake:comply,fake:refuse --runs 1 --guard off   (needs uv: see docs/BENCHMARK.md)

Every command except `bench` is standard library only, so it runs on a bare Python 3.9+.
"""

from __future__ import annotations

import argparse
import sys

from bench import ops


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dvap", description="DVAP: Damn Vulnerable Agentic Plant")
    sub = parser.add_subparsers(dest="command", required=True)

    up = sub.add_parser("up", help="start the lab (first run: creates .env and picks the LLM mode)")
    up.add_argument("--mode", choices=list(ops.MODES), help="LLM mode (default: ask on first run, else keep)")
    up.add_argument("--build", action="store_true", help="build the images from source instead of pulling")
    up.add_argument("--skip-checks", action="store_true", help="start even if `dvap doctor` fails")
    sub.add_parser("down", help="stop the lab (keeps all data)")
    reset = sub.add_parser("reset", help="wipe all lab state and restart (keeps the model), or reset one challenge")
    reset.add_argument("challenge", nargs="?", help="e.g. C01: reset just that challenge, in place")
    sub.add_parser("status", help="containers and UI health")
    logs = sub.add_parser("logs", help="follow the logs")
    logs.add_argument("service", nargs="?", help="e.g. agent-operator (default: all)")
    sub.add_parser("doctor", help="check Docker, memory, disk, CPU, ports and the LLM mode")
    demo = sub.add_parser("demo", help="run challenge C02 end to end against the running lab")
    demo.add_argument("--timeout", type=float, default=180, help="seconds to wait for the agent")
    sub.add_parser("version", help="DVAP, image, Docker and Compose versions")
    sub.add_parser("update", help="git pull, carry new settings into .env, pull the matching images")

    bench = sub.add_parser("bench", help="benchmark models (and the guard) against the challenges")
    bench.add_argument("--models", required=True,
                       help="comma-separated model specs: fake:comply, fake:refuse, ollama/<m>, anthropic/<m>, openai/<m>")
    bench.add_argument("--runs", type=int, default=3, help="runs per challenge (fixed seeds 0..N-1)")
    bench.add_argument("--guard", choices=["on", "off"], default="off", help="SafeEnvelope on or off")
    bench.add_argument("--challenges", default=None, help="comma-separated challenge ids (default: all)")
    bench.add_argument("--out", default="results", help="output root directory")
    return parser


def run_bench(args) -> int:
    try:
        import asyncio

        from bench.lab import now_stamp
        from bench.report import write_run
        from bench.runner import run_matrix
    except ImportError as e:
        print(f"`dvap bench` needs the Python dependencies ({e.name} is missing). Install uv "
              "(https://docs.astral.sh/uv/) and run: uv run dvap bench ...")
        return 1
    models = [m.strip() for m in args.models.split(",") if m.strip()]
    challenges = [c.strip() for c in args.challenges.split(",")] if args.challenges else None
    data = asyncio.run(run_matrix(models, args.runs, args.guard == "on", challenges))
    out = write_run(data, now_stamp(), args.out)
    print(f"wrote {out}/results.json, results.csv, report.html and updated README.md")
    return 0


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    commands = {
        "up": lambda: ops.up(args.mode, args.build, args.skip_checks),
        "down": ops.down,
        "reset": lambda: ops.reset(args.challenge),
        "status": ops.status,
        "logs": lambda: ops.logs(args.service),
        "doctor": lambda: 0 if ops.run_doctor(ops.read_env() if ops.ENV.exists() else ops.read_env(ops.ENV_EXAMPLE)) else 1,
        "demo": lambda: ops.demo(args.timeout),
        "version": ops.version,
        "update": ops.update,
        "bench": lambda: run_bench(args),
    }
    try:
        return commands[args.command]()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
