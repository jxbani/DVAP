"""Internal API for the PLC. Reachable on the docker network only (no published port)."""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from dvap_common import Actuators, PlantState
from plant_sim.plant import Plant

plant = Plant(
    seed=int(os.environ.get("PLANT_SEED", "0")),
    noise=os.environ.get("PLANT_NOISE", "0") == "1",
)
speed = 1  # plant seconds per wall-clock second; only the staged demo raises it, every reset restores 1


async def _tick_loop() -> None:
    # shortcut: sleep-based pacing drifts slightly behind wall-clock time;
    # schedule against loop.time() if the plant ever needs to stay in real-time sync.
    while True:
        for _ in range(speed):
            plant.step()
        await asyncio.sleep(1 / plant.consts.tick_hz)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_tick_loop())
    yield
    task.cancel()


app = FastAPI(title="DVAP plant-sim", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/state")
def get_state() -> PlantState:
    return plant.measured


@app.post("/actuators")
def post_actuators(changes: Actuators) -> PlantState:
    plant.set_actuators(changes)
    return plant.state


class SpeedBody(BaseModel):
    speed: int = Field(ge=1, le=10)


@app.post("/speed")
def set_speed(body: SpeedBody) -> dict:
    """Run the plant clock faster than real time (`./dvap demo` fits two incidents into 4 minutes)."""
    global speed
    speed = body.speed
    return {"ok": True, "speed": speed}


class ResetBody(BaseModel):
    seed: int | None = None


@app.post("/reset")
def reset(body: ResetBody | None = None) -> dict:
    """Restart the simulation from a clean initial state (used by a challenge reset)."""
    global plant, speed
    speed = 1
    seed = body.seed if body and body.seed is not None else int(os.environ.get("PLANT_SEED", "0"))
    plant = Plant(seed=seed, noise=os.environ.get("PLANT_NOISE", "0") == "1")
    return {"ok": True, "seed": seed}
