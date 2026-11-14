"""Builds the World a challenge is judged against.

Tool calls and the notes written to memory are not re-queryable, so they are accumulated from
the `agent.events` bus since the last reset. Plant incidents and PLC state are read live at
check time (they reflect the current, post-reset state).
"""

import asyncio
import json
import logging

import httpx
import redis.asyncio as redis

from scoreboard.schema import World

log = logging.getLogger("scoreboard")


class Checker:
    def __init__(self, plant_url: str, historian_url: str, redis_url: str):
        self.plant = httpx.AsyncClient(base_url=plant_url, timeout=3)
        self.historian = httpx.AsyncClient(base_url=historian_url, timeout=3)
        self.redis_url = redis_url
        self.tool_calls: list[dict] = []
        self.memory: list[str] = []

    def reset(self) -> None:
        self.tool_calls.clear()
        self.memory.clear()

    def consume(self, event: dict) -> None:
        if event.get("type") != "tool_call":
            return
        tool, args = event.get("tool"), event.get("args") or {}
        self.tool_calls.append({"tool": tool, "args": args})
        # shortcut: memory contents are tracked via the remember tool's events only; a writer
        # that bypasses the agent would be invisible. The agent is the only writer today.
        if tool == "remember":
            self.memory.append(str(args.get("content", "")))

    async def run(self) -> None:
        """Subscribe to agent.events forever, feeding consume()."""
        while True:
            try:
                async with redis.from_url(self.redis_url, decode_responses=True) as r, r.pubsub() as ps:
                    await ps.subscribe("agent.events")
                    async for msg in ps.listen():
                        if msg["type"] == "message":
                            try:
                                self.consume(json.loads(msg["data"]))
                            except (json.JSONDecodeError, TypeError):
                                pass
            except (redis.RedisError, OSError):
                log.warning("agent.events subscription dropped, retrying", exc_info=True)
                await asyncio.sleep(2)

    async def world(self) -> World:
        incidents: set[str] = set()
        plc: dict = {}
        try:
            s = (await self.plant.get("/state")).json()
            incidents = set(s.get("incidents", [])) | set(s.get("warnings", []))
        except httpx.HTTPError:
            pass
        try:
            plc = (await self.historian.get("/latest")).json().get("values") or {}
        except httpx.HTTPError:
            pass
        return World(incidents=incidents, tool_calls=list(self.tool_calls), plc=plc, memory=list(self.memory))

    async def aclose(self) -> None:
        await self.plant.aclose()
        await self.historian.aclose()
