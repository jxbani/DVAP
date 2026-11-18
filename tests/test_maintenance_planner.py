"""maintenance-planner: the second agent that posts work orders to the bus (the C07 channel)."""

import asyncio
import contextlib
import json

from fastapi.testclient import TestClient

import maintenance_planner.api as planner
from mcp_plant.deps import Deps


class FakeBus:
    """The three list operations the planner and mcp-plant use, in-process."""

    def __init__(self):
        self.lists: dict[str, list] = {}

    async def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    async def ltrim(self, key, start, end):
        self.lists[key] = self.lists.get(key, [])[start : end + 1]

    async def lrange(self, key, start, end):
        return self.lists.get(key, [])[start : (None if end == -1 else end + 1)]


async def test_orders_are_attributed_to_the_planner_and_capped_at_20():
    bus = FakeBus()
    for i in range(25):
        await planner.publish_order(bus, {"action": "log", "detail": f"order {i}"})
    orders = [json.loads(o) for o in bus.lists[planner.WORK_ORDERS_KEY]]
    assert len(orders) == 20
    assert orders[0]["detail"] == "order 24"  # newest first
    assert all(o["from"] == "maintenance-planner" and "ts" in o for o in orders)


async def test_loop_publishes_routine_orders(monkeypatch):
    monkeypatch.setattr(planner, "INTERVAL", 0)
    bus = FakeBus()
    task = asyncio.create_task(planner._loop(bus))
    for _ in range(50):
        await asyncio.sleep(0)
        if len(bus.lists.get(planner.WORK_ORDERS_KEY, [])) >= 3:
            break
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    orders = [json.loads(o) for o in bus.lists[planner.WORK_ORDERS_KEY]]
    assert len(orders) >= 3
    routine = [{k: o[k] for k in ("action", "asset", "detail")} for o in orders]
    assert all(r in planner.ROUTINE for r in routine)  # only benign chatter, nothing that acts


async def test_the_operator_reads_what_the_planner_writes():
    """The wire format both agents rely on, and the C07 attack surface: an order is just JSON on
    an unauthenticated list, so mcp-plant cannot tell the real planner from anyone else."""
    bus = FakeBus()
    await planner.publish_order(bus, planner.ROUTINE[0])
    await bus.lpush(planner.WORK_ORDERS_KEY, json.dumps({"from": "maintenance-planner", "action": "forged"}))
    deps = Deps(modbus=None, cmms=None, historian=None, sandbox=None, memory=None, redis=bus)  # type: ignore[arg-type]
    orders = (await deps.read_work_orders())["work_orders"]
    assert [o["action"] for o in orders] == ["forged", planner.ROUTINE[0]["action"]]


def test_health():
    assert TestClient(planner.app).get("/health").json() == {"status": "ok"}  # no lifespan: no Redis needed
