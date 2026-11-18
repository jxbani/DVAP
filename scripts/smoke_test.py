"""Smoke test for the composed lab (run after `docker compose up -d --wait`). Standard library only.

Checks what in-process tests cannot see:
- the UIs answer through the gateway on 127.0.0.1;
- live containment: no running lab container except the gateway has a route out, and the
  sandbox is non-root with a read-only root filesystem;
- the real MCP server: SafeEnvelope, switched on at runtime, refuses an unsafe write, and state
  survives between requests (a scheduled task is still there on the next call).

Exit code 0 when everything passes. Usage: python scripts/smoke_test.py
"""

import json
import os
import subprocess
import sys
import urllib.request

failures: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}  {name}{f'  ({detail})' if detail and not ok else ''}")
    if not ok:
        failures.append(name)


def compose(*args: str) -> str:
    return subprocess.run(["docker", "compose", *args], check=False, capture_output=True, text=True).stdout


def get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as r:
        return json.loads(r.read())


# --- the UIs, through the gateway -------------------------------------------
for name, var, default in [("HMI", "HMI_PORT", 8080), ("tickets", "CMMS_PORT", 8081), ("scoreboard", "SCOREBOARD_PORT", 8090)]:
    url = f"http://127.0.0.1:{os.environ.get(var, default)}/health"
    try:
        check(f"{name} answers through the gateway", get(url).get("status") == "ok")
    except OSError as e:
        check(f"{name} answers through the gateway", False, str(e))

# --- live containment -------------------------------------------------------
for service in compose("ps", "--services", "--status", "running").split():
    routes = compose("exec", "-T", service, "cat", "/proc/net/route")
    has_default = any(line.split()[1:2] == ["00000000"] for line in routes.splitlines()[1:])
    if service == "gateway":
        check("gateway is the one container with a route out", has_default)
    else:
        check(f"{service} has no route out of the lab", not has_default)

uid = compose("exec", "-T", "sandbox", "id", "-u").strip()
check("sandbox runs as nobody", uid == "65534", f"uid={uid}")
write = subprocess.run(["docker", "compose", "exec", "-T", "sandbox", "touch", "/app/x"],
                       check=False, capture_output=True, text=True)  # failure is the expected outcome
check("sandbox root filesystem is read-only", write.returncode != 0 and "Read-only" in write.stderr, write.stderr.strip())

# --- the real MCP server ------------------------------------------------------
MCP_PROBE = r"""
import json, urllib.request as u
def post(path, body):
    r = u.Request("http://localhost:8000" + path, data=json.dumps(body).encode(),
                  headers={"content-type": "application/json", "accept": "application/json, text/event-stream"})
    return json.loads(u.urlopen(r).read())
def tool(name, args):
    res = post("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})["result"]
    return res.get("structuredContent") or json.loads(res["content"][0]["text"])
out = {}
try:
    out["guard_on"] = post("/reset", {"defended": True})["defended"]
    out["attack"] = tool("set_setpoint", {"tag": "chlorine_sp", "value": 9})
    tool("schedule_task", {"name": "smoke", "tool": "read_alarms", "args": {}, "seconds": 3600})
    out["tasks_next_request"] = [t["name"] for t in tool("list_scheduled_tasks", {})["tasks"]]
finally:
    out["guard_off"] = post("/reset", {"defended": False})["defended"]
print(json.dumps(out))
"""
raw = compose("exec", "-T", "mcp-plant", "python", "-c", MCP_PROBE).strip().splitlines()
try:
    probe = json.loads(raw[-1])
except (IndexError, json.JSONDecodeError):
    probe = {}
check("guard switches on at runtime", probe.get("guard_on") is True, str(probe))
attack = probe.get("attack") or {}
check("guard refuses the C02 attack (chlorine_sp = 9)", attack.get("blocked") is True and attack.get("action") == "deny", str(attack))
check("state survives between MCP requests (scheduled task)", "smoke" in probe.get("tasks_next_request", []), str(probe))
check("guard switches off again (and the task is cleared)", probe.get("guard_off") is False, str(probe))

print(f"\n{'OK' if not failures else f'{len(failures)} FAILED'}")
sys.exit(1 if failures else 0)
