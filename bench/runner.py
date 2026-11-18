"""Runs the benchmark matrix: for each model and challenge, N seeded runs of the attack scenario,
recording attack success, time-to-incident, tool calls and tokens (and, with the guard on, the
block rate and the benign-workload false-positive rate). Deterministic physics; seeds are logged.
"""

import os
import statistics
import time
from typing import Any

import httpx

import vendor_analytics.server as vendor
from agent_operator.agent import SYSTEM_PROMPT
from agent_operator.llm import FakeLLM, LiteLLMClient
from bench.lab import Lab
from bench.scenarios import BENIGN_PROMPT, SCENARIOS, run_benign
from scoreboard.schema import load_challenges

OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://localhost:11434")
CHALLENGES = load_challenges(os.environ.get("CHALLENGES_DIR", "challenges"))


def resolve_version(spec: str) -> str:
    if spec.startswith("fake:"):
        return "deterministic-fake"
    if spec.startswith("ollama/"):
        try:
            return httpx.get(f"{OLLAMA_API_BASE}/api/version", timeout=3).json().get("version", "unknown")
        except Exception:  # noqa: BLE001 - version is best-effort metadata
            return "unknown"
    return "provider-managed"


def _llm_for(spec: str, scenario, run):
    if spec == "fake:comply":
        return FakeLLM(scenario.comply(run))
    if spec == "fake:refuse":
        return FakeLLM([])
    kwargs = {"api_base": OLLAMA_API_BASE} if spec.startswith("ollama/") else {}
    return LiteLLMClient(spec, **kwargs)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.fmean(xs), 2) if xs else None


async def run_matrix(models: list[str], runs: int, guard: bool, challenges: list[str] | None = None) -> dict:
    challenges = challenges or list(SCENARIOS)
    seeds = list(range(runs))
    results: list[dict] = []
    benign = None

    async with Lab.create() as lab:
        if guard:  # the benign false-positive rate is a property of the guard, so measure it once
            await lab.reset("easy", 0)
            async with lab.run(guard=True, with_vendor=False) as run:
                decisions, false_positives = await run_benign(run)
            benign = {"decisions": decisions, "false_positives": false_positives,
                      "fp_rate": round(false_positives / decisions, 3) if decisions else 0.0}

        for model in models:
            for cid in challenges:
                sc, ch = SCENARIOS[cid], CHALLENGES[cid]
                per_run = []
                for i in seeds:
                    await lab.reset(sc.difficulty, i)
                    if sc.pre_rugpull:
                        vendor._set_description(vendor.POISONED)  # poison before the agent lists the tools (C04)
                    async with lab.run(guard=guard, with_vendor=sc.vendor) as run:
                        agent = run.make_agent(_llm_for(model, sc, run))
                        row: dict[str, Any] = {"run": i, "seed": i}
                        try:
                            tti = await sc.drive(run, agent)
                            world = await run.world()
                            blocked = [d for d in run.guard_decisions if d.get("action") != "allow"]
                            row |= {
                                "success": ch.success_condition.evaluate(world),
                                "time_to_incident_s": tti,
                                "tool_calls": sum(1 for e in run.bus.published if e.get("type") == "tool_call"),
                                "llm_calls": run.metered.calls,
                                "tokens": run.metered.tokens,
                                "guard_blocked": len(blocked),
                                "guard_decisions": len(run.guard_decisions),
                            }
                        except Exception as e:  # noqa: BLE001 - a model/transport failure must not abort the matrix
                            row |= {"success": False, "error": f"{type(e).__name__}: {e}"}
                        per_run.append(row)

                ok = [r for r in per_run if "error" not in r]
                successes = [r for r in ok if r.get("success")]
                results.append({
                    "model": model,
                    "challenge": cid,
                    "asi": ch.owasp_asi,
                    "title": ch.title,
                    "success_rate": round(len(successes) / len(per_run), 3) if per_run else 0.0,
                    "mean_tool_calls": _mean([r.get("tool_calls") for r in ok]),
                    "mean_tokens": _mean([r.get("tokens") for r in ok]),
                    "mean_time_to_incident_s": _mean([r.get("time_to_incident_s") for r in ok]),
                    "block_rate": (round(sum(1 for r in ok if r.get("guard_blocked")) / len(ok), 3)
                                   if guard and ok else None),
                    "runs": per_run,
                })

    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "config": {"models": models, "runs": runs, "guard": "on" if guard else "off",
                   "seeds": seeds, "challenges": challenges},
        "environment": {"model_versions": {m: resolve_version(m) for m in models}},
        "benign": benign,
        "prompts": {
            "system_prompt": SYSTEM_PROMPT,
            "benign_workload": BENIGN_PROMPT,
            "attacks": {cid: SCENARIOS[cid].injection for cid in challenges},
            "objectives": {cid: CHALLENGES[cid].objective.strip() for cid in challenges},
        },
        "results": results,
    }
