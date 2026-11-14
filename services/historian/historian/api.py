"""Historian query API. Internal docker network only."""

import asyncio
import os
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, HTTPException, Query

from dvap_common.plc_tags import TAGS
from historian.collector import Collector
from historian.store import Store

NUMERIC_TAGS = {t.name for t in TAGS if not t.chars}

# Replaced in the lifespan (and by tests).
store = Store()
collector = Collector(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global store, collector
    store = Store(os.environ.get("HISTORIAN_DB", "/data/historian.sqlite"))
    collector = Collector(store, os.environ.get("PLC_HOST", "plc"), int(os.environ.get("PLC_PORT", "502")))
    task = asyncio.create_task(collector.run())
    yield
    task.cancel()


app = FastAPI(title="DVAP historian", lifespan=lifespan)

# Handlers are async on purpose: everything touches SQLite from the one event-loop thread.


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "last_poll": collector.latest_ts}


@app.get("/latest")
async def latest() -> dict:
    """The most recent value of every tag, strings included."""
    return {"ts": collector.latest_ts, "values": collector.latest}


@app.post("/reset")
async def reset() -> dict:
    """Drop the stored time series and events (used by a challenge reset)."""
    store.clear()
    return {"ok": True}


@app.get("/series")
async def series(
    tag: str,
    start: Annotated[float | None, Query(alias="from", description="epoch seconds, default 10 min ago")] = None,
    end: Annotated[float | None, Query(alias="to", description="epoch seconds, default now")] = None,
) -> dict:
    if tag not in NUMERIC_TAGS:
        raise HTTPException(404, f"unknown tag {tag!r}")
    end = time.time() if end is None else end
    start = end - 600 if start is None else start
    return {"tag": tag, "points": store.series(tag, start, end)}


@app.get("/events")
async def events(limit: Annotated[int, Query(ge=1, le=1000)] = 100, kind: str | None = None) -> dict:
    """Incidents, warnings, alarms and mode changes, newest first."""
    return {"events": store.events(limit, kind)}
