"""PLC service entrypoint: starts the Modbus/OPC UA servers, the scan loop and /health."""

import asyncio
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from pydantic import BaseModel

from plc.plc import Plc

DIFFICULTY = os.environ.get("PLC_DIFFICULTY", "easy")
PLANT_URL = os.environ.get("PLANT_URL", "http://plant-sim:8000")

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(base_url=PLANT_URL, timeout=2) as http:
        plc = state["plc"] = Plc(http, DIFFICULTY)
        await plc.start()
        task = asyncio.create_task(plc.run())
        yield
        task.cancel()
        await plc.stop()


app = FastAPI(title="DVAP plc", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    plc = state.get("plc")
    return {"status": "ok", "difficulty": DIFFICULTY, "plant_reachable": bool(plc and plc.healthy)}


class ResetBody(BaseModel):
    difficulty: str | None = None  # easy | medium | hard


@app.post("/reset")
def reset(body: ResetBody | None = None) -> dict:
    plc = state["plc"]
    plc.reset(body.difficulty if body else None)
    return {"ok": True, "difficulty": plc.difficulty}
