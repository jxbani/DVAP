"""A thin LLM seam so the agent loop never imports a provider directly.

`LiteLLMClient` talks to any model LiteLLM supports (Ollama by default). `ReplayLLM` plays back
recorded responses (`MODEL=replay`, no model needed). `FakeLLM` replays scripted replies so tests
never need a real model.
"""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

# Lab safety: LiteLLM otherwise downloads its model price list and other catalogs from GitHub on
# import. Offline mode uses its bundled copies; calls to the configured model endpoint still work.
# Set here, before LiteLLM is ever imported, so it covers the agent container and `dvap bench`.
os.environ.setdefault("LITELLM_OFFLINE_MODE", "true")


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: dict | None = None  # {prompt_tokens, completion_tokens, total_tokens} when the provider reports it


class LLM(Protocol):
    async def chat(self, messages: list[dict], tools: list[dict]) -> Reply: ...


class LiteLLMClient:
    def __init__(self, model: str, **kwargs):
        self.model = model
        self.kwargs = kwargs  # e.g. api_base for Ollama/OpenAI-compatible endpoints

    async def chat(self, messages: list[dict], tools: list[dict]) -> Reply:
        import litellm

        resp = await litellm.acompletion(
            model=self.model, messages=messages, tools=tools or None, temperature=0, **self.kwargs
        )
        msg = resp.choices[0].message
        calls = []
        for tc in msg.tool_calls or []:
            raw = tc.function.arguments
            args = raw if isinstance(raw, dict) else json.loads(raw or "{}")
            calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))
        usage = getattr(resp, "usage", None)
        if usage is not None and hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        return Reply(content=msg.content or "", tool_calls=calls, usage=usage)


REPLAY_FILE = Path(__file__).with_name("replay.json")


class ReplayLLM:
    """`MODEL=replay`: plays back recorded responses, so the lab runs with no model at all.

    Each recording pairs a pattern seen in the agent's context (ticket text, work orders, ...)
    with the tool calls a naive model made in response. The first recording that matches and
    still has calls this turn has not made yet supplies the next call; otherwise it writes a
    shift-log line. It falls for the textbook attack phrasings and nothing cleverer: it is for
    exploring the lab without a GPU or an API key, not for benchmarking (use `dvap bench`).
    """

    def __init__(self, path: Path = REPLAY_FILE):
        self.recordings = json.loads(path.read_text(encoding="utf-8"))

    async def chat(self, messages: list[dict], tools: list[dict]) -> Reply:
        seen = "\n".join(str(m.get("content") or "") for m in messages if m["role"] in ("user", "tool"))
        made = [
            (tc["function"]["name"], json.loads(tc["function"]["arguments"]))
            for m in messages if m["role"] == "assistant" for tc in m.get("tool_calls") or []
        ]
        # The snapshot lists ticket titles only; like a model, read the newest open ones first
        # (attacker tickets are the newest; three leaves room in the step budget to act).
        for ticket_id in sorted(_open_ticket_ids(messages), reverse=True)[:READ_NEWEST]:
            if ("read_ticket", {"ticket_id": ticket_id}) not in made:
                return Reply(content="Reviewing an open ticket.", tool_calls=[
                    ToolCall(id=f"replay-{len(made)}", name="read_ticket", arguments={"ticket_id": ticket_id})])
        for rec in self.recordings:
            match = re.search(rec["when"], seen, re.IGNORECASE)
            if not match:
                continue
            for call in rec["calls"]:
                args = {k: _fill(v, match) for k, v in call["arguments"].items()}
                if (call["name"], args) not in made:
                    return Reply(content=rec["say"], tool_calls=[ToolCall(id=f"replay-{len(made)}", name=call["name"], arguments=args)])
        acted = sum(name != "read_ticket" for name, _ in made)
        if acted:
            return Reply(content=f"Shift log: carried out {acted} requested action(s).")
        return Reply(content="Shift log: plant within limits, nothing to do.")


READ_NEWEST = 3


def _open_ticket_ids(messages: list[dict]) -> list[int]:
    """Ticket ids from the plant snapshot ("...snapshot:\\n{json}...") in the user messages."""
    for m in messages:
        text = str(m.get("content") or "") if m["role"] == "user" else ""
        if "{" in text:
            try:
                snapshot = json.loads(text[text.index("{"): text.rindex("}") + 1])
            except ValueError:
                continue
            return [t["id"] for t in snapshot.get("open_tickets") or [] if isinstance(t, dict) and "id" in t]
    return []


def _fill(value, match: re.Match):
    """"$name" in a recording is replaced by the named group from its pattern (numbers as floats)."""
    if isinstance(value, str) and value.startswith("$"):
        got = match.group(value[1:])
        try:
            return float(got)
        except ValueError:
            return got
    return value


class FakeLLM:
    """Replays scripted replies in order. Each entry is a Reply or a callable(messages)->Reply."""

    def __init__(self, script: list):
        self.script = list(script)
        self.calls: list[list[dict]] = []

    async def chat(self, messages: list[dict], tools: list[dict]) -> Reply:
        self.calls.append(messages)
        if not self.script:
            return Reply(content="(no more scripted replies)")
        step = self.script.pop(0)
        return step(messages) if callable(step) else step
