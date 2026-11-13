"""Internal API for the PLC. Reachable on the docker network only (no published port)."""

import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from dvap_common import Actuators, PlantState
from plant_sim.plant import Plant

plant = Plant(
    seed=int(os.environ.get("PLANT_SEED", "0")),
    noise=os.environ.get("PLANT_NOISE", "0") == "1",
)


async def _tick_loop() -> None:
    # shortcut: sleep-based pacing drifts slightly behind wall-clock time;
    # schedule against loop.time() if the plant ever needs to stay in real-time sync.
    while True:
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
