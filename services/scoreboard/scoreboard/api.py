"""Scoreboard service: lists challenges, resets the stack per challenge, watches the lab for
each challenge's success condition, and mints/verifies flags. Published on 127.0.0.1:8090.

Classroom/CTF mode: run one isolated stack per team with a compose project name
(`docker compose -p team1 ...`), each with its own TEAM and the same DVAP_FLAG_SECRET, so a
flag captured on one stack verifies on a central board. See docs/CHALLENGE_AUTHORING.md.
"""

import asyncio
import contextlib
import logging
import os
from pathlib import Path

import httpx
import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from scoreboard.checker import Checker
from scoreboard.flags import make_flag, verify_flag
from scoreboard.schema import Challenge, load_challenges

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("scoreboard")

TEAM = os.environ.get("TEAM", "solo")
FLAG_SECRET = os.environ.get("DVAP_FLAG_SECRET", "dvap-dev-secret")
CHALLENGES_DIR = os.environ.get("CHALLENGES_DIR", "challenges")
REDIS_URL = os.environ.get("REDIS_URL", "redis://bus:6379")
SERVICES = {  # service -> base URL; each exposes POST /reset
    "plant-sim": os.environ.get("PLANT_URL", "http://plant-sim:8000"),
    "plc": os.environ.get("PLC_URL", "http://plc:8000"),
    "cmms": os.environ.get("CMMS_URL", "http://cmms:8000"),
    "historian": os.environ.get("HISTORIAN_URL", "http://historian:8000"),
    "mcp-plant": os.environ.get("MCP_URL", "http://mcp-plant:8000"),
    "vendor-analytics": os.environ.get("VENDOR_URL", "http://vendor-analytics:8000"),
}
STATIC = Path(__file__).with_name("static")

CHALLENGES: dict[str, Challenge] = load_challenges(CHALLENGES_DIR)
checker = Checker(SERVICES["plant-sim"], SERVICES["historian"], REDIS_URL)
# Per challenge: {"solved": bool, "flag": str | None}. One team per stack (see module docstring).
status: dict[str, dict] = {cid: {"solved": False, "flag": None} for cid in CHALLENGES}
active: str | None = None


async def reset_stack(challenge: Challenge) -> None:
    """Restore every service to the challenge's clean starting state, and clear the checker."""
    setup = challenge.setup
    bodies = {
        "plant-sim": {"seed": setup.seed},
        "plc": {"difficulty": setup.difficulty},
        "cmms": {},
        "historian": {},
        "mcp-plant": {},
        "vendor-analytics": {},  # restores the benign tool description (undoes the C04 rug-pull)
    }
    async with httpx.AsyncClient(timeout=10) as c:
        for name, url in SERVICES.items():
            with contextlib.suppress(httpx.HTTPError):
                await c.post(f"{url}/reset", json=bodies[name])
    with contextlib.suppress(redis.RedisError, OSError):
        r = redis.from_url(REDIS_URL)
        await r.flushdb()
        await r.aclose()
    checker.reset()


async def _watch() -> None:
    """Mark the active challenge solved as soon as its success condition holds."""
    while True:
        await asyncio.sleep(2)
        cid = active
        if cid is None or status[cid]["solved"]:
            continue
        try:
            if CHALLENGES[cid].success_condition.evaluate(await checker.world()):
                _mark_solved(cid)
                log.info("challenge %s solved by team %s", cid, TEAM)
        except Exception:
            log.warning("checker failed for %s", cid, exc_info=True)


def _mark_solved(cid: str) -> None:
    status[cid] = {"solved": True, "flag": make_flag(FLAG_SECRET, TEAM, cid)}


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    tasks = [asyncio.create_task(checker.run()), asyncio.create_task(_watch())]
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await checker.aclose()


app = FastAPI(title="DVAP scoreboard", lifespan=lifespan)


def _public(cid: str) -> dict:
    ch = CHALLENGES[cid]
    return {
        **ch.model_dump(exclude={"success_condition"}),
        "solved": status[cid]["solved"],
        "flag": status[cid]["flag"],
        "active": cid == active,
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "team": TEAM, "challenges": len(CHALLENGES)}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/challenges")
async def challenges() -> dict:
    return {"team": TEAM, "active": active, "challenges": [_public(cid) for cid in CHALLENGES]}


@app.post("/api/challenges/{cid}/start")
async def start(cid: str) -> dict:
    """Make a challenge active and reset the stack to its clean starting state."""
    global active
    if cid not in CHALLENGES:
        raise HTTPException(404, f"no challenge {cid}")
    active = cid
    await reset_stack(CHALLENGES[cid])
    return _public(cid)


@app.post("/api/challenges/{cid}/reset")
async def reset(cid: str) -> dict:
    if cid not in CHALLENGES:
        raise HTTPException(404, f"no challenge {cid}")
    await reset_stack(CHALLENGES[cid])
    return {"ok": True}


class FlagIn(BaseModel):
    flag: str


@app.post("/api/flag")
async def submit_flag(body: FlagIn) -> dict:
    """Verify a pasted flag and mark that challenge solved (for a central CTF board)."""
    cid = verify_flag(FLAG_SECRET, TEAM, body.flag)
    if cid is None or cid not in CHALLENGES:
        return {"ok": False, "reason": "invalid flag for this team"}
    _mark_solved(cid)
    return {"ok": True, "challenge": cid}
