"""agent-operator service: runs the operator agent on a timer and lets a supervisor talk to it.

Connects to mcp-plant over MCP (streamable HTTP) and publishes the agent's reasoning and
shift logs to the Redis `agent.events` channel (the HMI's "Agent activity" panel).
"""

import asyncio
import contextlib
import json
import logging
import os

import redis.asyncio as redis
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel

from agent_operator.agent import Agent
from agent_operator.llm import LLM, LiteLLMClient, ReplayLLM

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("agent-operator")

MCP_URL = os.environ.get("MCP_URL", "http://mcp-plant:8000/mcp")
VENDOR_MCP_URL = os.environ.get("VENDOR_MCP_URL")  # optional third-party MCP server (C04)
REDIS_URL = os.environ.get("REDIS_URL", "redis://bus:6379")
MODEL = os.environ.get("MODEL", "ollama/qwen2.5:7b-instruct")
OLLAMA_API_BASE = os.environ.get("OLLAMA_API_BASE", "http://ollama:11434")
CYCLE_SECONDS = float(os.environ.get("AGENT_CYCLE_SECONDS", "30"))
AUTOSTART = os.environ.get("AGENT_AUTOSTART", "1") == "1"

state: dict = {}
cycle_lock = asyncio.Lock()  # the timer loop and POST /cycle never run two cycles at once


def llm_from_env() -> LLM:
    if MODEL == "replay":  # recorded responses, no model needed (DVAP_LLM_MODE=replay)
        return ReplayLLM()
    # Ollama needs an api_base; hosted providers (anthropic/*, openai/*) ignore it and use their keys.
    kwargs = {"api_base": OLLAMA_API_BASE} if MODEL.startswith("ollama/") else {}
    return LiteLLMClient(MODEL, **kwargs)


async def _cycle_loop(agent: Agent) -> None:
    while True:
        try:
            async with cycle_lock:
                log.info("shift log: %s", await agent.cycle())
        except Exception:
            log.exception("agent cycle failed")
        await asyncio.sleep(CYCLE_SECONDS)


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    bus = redis.from_url(REDIS_URL)

    async def publish(event: dict) -> None:
        with contextlib.suppress(Exception):
            await bus.publish("agent.events", json.dumps(event, default=str))

    async with (
        streamablehttp_client(MCP_URL) as (read, write, _),
        ClientSession(read, write) as session,
        contextlib.AsyncExitStack() as extra_stack,
    ):
        await session.initialize()
        tools = (await session.list_tools()).tools
        extra = []
        if VENDOR_MCP_URL:  # connect the third-party server; its tool descriptions reach the agent (C04)
            vr, vw, _ = await extra_stack.enter_async_context(streamablehttp_client(VENDOR_MCP_URL))
            vsession = await extra_stack.enter_async_context(ClientSession(vr, vw))
            await vsession.initialize()
            extra.append((vsession, (await vsession.list_tools()).tools))
        agent = state["agent"] = Agent(llm_from_env(), session, tools, publish=publish, extra=extra)
        task = asyncio.create_task(_cycle_loop(agent)) if AUTOSTART else None
        try:
            yield
        finally:
            if task:
                task.cancel()
            await bus.aclose()


app = FastAPI(title="DVAP agent-operator", lifespan=lifespan)


class ChatIn(BaseModel):
    message: str


class ApproveIn(BaseModel):
    id: str
    decision: str  # "approve" | "reject"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "model": MODEL, "connected": "agent" in state}


@app.post("/chat")
async def chat(body: ChatIn) -> dict:
    return {"reply": await state["agent"].chat(body.message)}


@app.post("/cycle")
async def cycle_now() -> dict:
    """Run one agent cycle now instead of waiting for the timer (the staged demo's fixed timings)."""
    async with cycle_lock:
        return {"log": await state["agent"].cycle()}


@app.get("/log")
async def shift_log(limit: int = 20) -> dict:
    return {"log": state["agent"].shift_log[-limit:]}


@app.get("/approvals")
async def approvals() -> dict:
    pending = [a.public() for a in state["agent"].approvals.values() if a.status == "pending"]
    return {"approvals": pending}


@app.post("/approve")
async def approve(body: ApproveIn) -> dict:
    return await state["agent"].approve(body.id, body.decision)
