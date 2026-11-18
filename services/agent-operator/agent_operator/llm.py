"""A thin LLM seam so the agent loop never imports a provider directly.

`LiteLLMClient` talks to any model LiteLLM supports (Ollama by default). `FakeLLM` replays
scripted replies so tests never need a real model.
"""

import json
import os
from dataclasses import dataclass, field
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
