"""A tiny recurring-task scheduler. DVAP-VULN: C10 - exposed to the operator agent, it lets a
hijacked agent plant a task that re-applies an unsafe action after operators fix it. The
defensive control is detection (list the tasks) and a kill switch (clear)."""

import asyncio
import logging
import time
from dataclasses import asdict, dataclass

log = logging.getLogger("mcp-plant")


@dataclass
class Task:
    name: str
    tool: str
    args: dict
    seconds: float
    next_run: float


class Scheduler:
    def __init__(self, run_tool):
        self.run_tool = run_tool  # async callable(tool: str, args: dict)
        self.tasks: dict[str, Task] = {}

    def schedule(self, name: str, tool: str, args: dict, seconds: float) -> Task:
        self.tasks[name] = Task(name, tool, args, seconds, time.time() + seconds)
        return self.tasks[name]

    def list(self) -> list[dict]:
        return [asdict(t) for t in self.tasks.values()]

    def clear(self) -> None:
        self.tasks.clear()

    async def run_due(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        for task in list(self.tasks.values()):
            if now >= task.next_run:
                await self.run_tool(task.tool, task.args)
                task.next_run = now + task.seconds

    async def run(self) -> None:
        while True:
            await asyncio.sleep(1)
            try:
                await self.run_due()
            except Exception:
                log.warning("scheduled task failed", exc_info=True)
