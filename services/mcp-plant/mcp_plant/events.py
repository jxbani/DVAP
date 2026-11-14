"""Publishing every tool call to the Redis `agent.events` channel.

Each call emits two events: a `tool_call` with the arguments, then a `tool_result` with a
short summary. Both carry the IDs of the context items that were in the agent's prompt when
it made the call, so an observer can see which (possibly untrusted) context drove an action.
"""

import json
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

log = logging.getLogger("mcp-plant")
CHANNEL = "agent.events"


def context_ids(ctx) -> list[str]:
    """The `context_ids` the caller passed in the MCP request `_meta`, if any."""
    meta = getattr(getattr(ctx, "request_context", None), "meta", None)
    if meta is None:
        return []
    ids = getattr(meta, "context_ids", None)
    if ids is None and hasattr(meta, "model_dump"):
        ids = meta.model_dump().get("context_ids")
    return list(ids) if isinstance(ids, (list, tuple)) else []


@dataclass
class _Tracked:
    summary: str = ""


@dataclass
class EventBus:
    redis: object | None = None  # redis.asyncio client, or None to only buffer
    published: list[dict] = field(default_factory=list)

    async def publish(self, event: dict) -> dict:
        event = {"ts": time.time(), **event}
        self.published.append(event)
        if self.redis is not None:
            try:
                await self.redis.publish(CHANNEL, json.dumps(event, default=str))
            except Exception:
                log.warning("could not publish to %s", CHANNEL, exc_info=True)
        return event

    @asynccontextmanager
    async def track(self, ctx, tool: str, args: dict):
        ids = context_ids(ctx)
        await self.publish({"type": "tool_call", "tool": tool, "args": args, "context_ids": ids})
        tracked = _Tracked()
        try:
            yield tracked
        except Exception as e:
            await self.publish(
                {"type": "tool_result", "tool": tool, "ok": False, "summary": f"error: {e}", "context_ids": ids}
            )
            raise
        await self.publish(
            {"type": "tool_result", "tool": tool, "ok": True, "summary": tracked.summary, "context_ids": ids}
        )
