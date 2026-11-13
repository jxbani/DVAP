"""HMI backend: serves the dashboard and gives it one small JSON API.

Read-only. It talks to plant-sim, the historian and Redis on the docker network and is
published to the host on 127.0.0.1:8080 only (see docker-compose.yml).
"""

import asyncio
import os
import time
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from dvap_common.plc_tags import INTERLOCKS, STATUS_BITS, flags

STATIC = Path(__file__).with_name("static")
REDIS_URL = os.environ.get("REDIS_URL", "redis://bus:6379")
AGENT_CHANNEL = "agent.events"

# Replaced by tests.
plant = httpx.AsyncClient(base_url=os.environ.get("PLANT_URL", "http://plant-sim:8000"), timeout=2)
historian = httpx.AsyncClient(base_url=os.environ.get("HISTORIAN_URL", "http://historian:8000"), timeout=2)

app = FastAPI(title="DVAP HMI")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


async def _get(client: httpx.AsyncClient, path: str, **params) -> dict | None:
    """GET JSON from an upstream service, or None if it is down (the dashboard shows that)."""
    try:
        r = await client.get(path, params={k: v for k, v in params.items() if v is not None})
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/live")
async def live() -> dict:
    """Everything the dashboard needs for one refresh."""
    state, latest, incident_events = await asyncio.gather(
        _get(plant, "/state"),
        _get(historian, "/latest"),
        _get(historian, "/events", kind="incident", limit=50),
    )
    plc = (latest or {}).get("values") or None
    status = flags(plc["status"], STATUS_BITS) if plc else {}
    enabled = flags(plc["interlocks_enabled"], INTERLOCKS) if plc else {}

    # Incidents come from plant-sim (ground truth); the historian knows when each one started.
    started = {e["name"]: e["ts"] for e in reversed((incident_events or {}).get("events", []))}
    now = time.time()
    incidents = [{"name": n, "ts": started.get(n, now)} for n in (state or {}).get("incidents", [])]

    return {
        "ts": now,
        "plant": state,
        "plc": plc,
        "status": status,
        "interlocks": {k: {"enabled": enabled[k], "tripped": status[f"trip_{k}"]} for k in INTERLOCKS} if plc else {},
        "incidents": incidents,
    }


@app.get("/api/series")
async def series(request: Request) -> dict:
    """Pass-through to the historian (tag, from, to)."""
    return await _get(historian, "/series", **request.query_params) or {"points": []}


@app.get("/api/events")
async def events(limit: int = 50) -> dict:
    return await _get(historian, "/events", limit=limit) or {"events": []}


async def agent_events() -> AsyncIterator[str | None]:
    """Yield messages published on the Redis `agent.events` channel, forever.

    Yields None every 15 s of silence (and while Redis is unreachable) as a keepalive.
    """
    while True:
        try:
            async with redis.from_url(REDIS_URL, decode_responses=True) as bus, bus.pubsub() as pubsub:
                await pubsub.subscribe(AGENT_CHANNEL)
                while True:
                    message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15)
                    yield message["data"] if message else None
        except (redis.RedisError, OSError):
            yield None
            await asyncio.sleep(2)


def sse(data: str | None) -> str:
    """Format one Server-Sent Event. The payload is untrusted (anyone on the bus can publish),
    so every line gets its own `data:` prefix: a message cannot smuggle in extra SSE fields."""
    if data is None:
        return ": keepalive\n\n"
    return "".join(f"data: {line}\n" for line in data.splitlines() or [""]) + "\n"


@app.get("/api/agent/stream")
async def agent_stream() -> StreamingResponse:
    async def body():
        yield sse(None)  # flush headers so the browser sees the stream open
        async for data in agent_events():
            yield sse(data)

    return StreamingResponse(body(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
