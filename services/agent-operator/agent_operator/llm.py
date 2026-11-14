"""A thin LLM seam so the agent loop never imports a provider directly.

`LiteLLMClient` talks to any model LiteLLM supports (Ollama by default). `FakeLLM` replays
scripted replies so tests never need a real model.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Reply:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


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
        return Reply(content=msg.content or "", tool_calls=calls)


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
        return step(messages) if isinstance(step, Callable) else step
