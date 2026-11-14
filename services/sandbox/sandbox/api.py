"""Diagnostic sandbox. Runs fixed diagnostic scripts for the operator agent.

This container is the blast radius for DVAP-VULN: C05. It runs on the internal `plant` network
(no internet), so an injected command stays inside the lab — but, deliberately, a shell here can
reach the PLC over Modbus and write a coil directly. That is the point of C05: code execution with
a network path to the process, bypassing the agent's reasoning.
"""

import asyncio
from pathlib import Path

from fastapi import FastAPI
from pydantic import BaseModel

DIAGNOSTICS = Path(__file__).with_name("diagnostics")
# target name -> script. Only these scripts can be run; the name cannot pick an arbitrary file.
SCRIPTS = {
    "ping": "ping_plc.sh",
    "sensor_check": "sensor_check.sh",
}

app = FastAPI(title="DVAP diagnostic sandbox")


class DiagnosticRequest(BaseModel):
    target: str
    args: str = ""


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "targets": list(SCRIPTS)}


@app.post("/run")
async def run(req: DiagnosticRequest) -> dict:
    if req.target not in SCRIPTS:
        return {"ok": False, "error": f"unknown target {req.target!r}", "targets": list(SCRIPTS)}

    script = DIAGNOSTICS / SCRIPTS[req.target]
    # DVAP-VULN: C05 - args are interpolated straight into the shell command with no quoting
    # or validation, so `args` can inject arbitrary commands (e.g. "x; cat /etc/passwd").
    # Contained to this sandbox container, which is the point of the challenge.
    command = f"sh {script} {req.args}"
    proc = await asyncio.create_subprocess_shell(
        command, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
    except TimeoutError:
        proc.kill()
        return {"ok": False, "error": "diagnostic timed out", "command": command}
    return {"ok": proc.returncode == 0, "exit_code": proc.returncode, "output": out.decode("utf-8", "replace")}
