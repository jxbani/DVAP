"""DVAP benchmark harness: run attack scenarios across models and the guard, and report.

The services live under services/<name>/<package> and are normally put on sys.path by pytest.
For the `dvap` CLI (run from the repo root) we do the same here so the service packages import.
"""

import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SERVICES = [
    "plant-sim", "plc", "historian", "hmi", "cmms", "agent-operator",
    "mcp-plant", "sandbox", "scoreboard", "vendor-analytics", "maintenance-planner",
]
for _name in _SERVICES:
    _path = str(_REPO / "services" / _name)
    if _path not in sys.path:
        sys.path.insert(0, _path)
