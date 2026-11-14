"""Challenge definition schema and the success-condition evaluator.

A challenge.yaml validates against `Challenge`. A `Condition` is evaluated against a `World`
snapshot the checker builds from plant incidents, the agent tool-call log, PLC state and the
notes written to memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

ASI = Literal["ASI01", "ASI02", "ASI03", "ASI04", "ASI05", "ASI06", "ASI07", "ASI08", "ASI09", "ASI10"]
COMPARATORS = {
    "eq": lambda a, b: a == b,
    "ne": lambda a, b: a != b,
    "ge": lambda a, b: a >= b,
    "gt": lambda a, b: a > b,
    "le": lambda a, b: a <= b,
    "lt": lambda a, b: a < b,
}


@dataclass
class World:
    """What has happened in the lab since the challenge was reset."""

    incidents: set[str] = field(default_factory=set)  # plant incident names seen
    tool_calls: list[dict] = field(default_factory=list)  # {"tool": str, "args": dict}
    plc: dict = field(default_factory=dict)  # current PLC tag -> value
    memory: list[str] = field(default_factory=list)  # contents written via the remember tool


class Condition(BaseModel):
    """A success condition. Exactly one form per node; combine with all_of / any_of / not_."""

    model_config = ConfigDict(extra="forbid")

    all_of: list[Condition] | None = None
    any_of: list[Condition] | None = None
    not_: Condition | None = Field(None, alias="not")
    incident: str | None = None  # this plant incident occurred
    tool_called: str | None = None  # the agent called this tool...
    with_args: dict | None = None  # ...with these exact arg values, and/or...
    args_contains: str | None = None  # ...with this text somewhere in its args
    plc: dict[str, dict[str, float]] | None = None  # tag -> {comparator: value}
    memory_contains: str | None = None  # a note written to memory contains this text (case-insensitive)

    @model_validator(mode="after")
    def _exactly_one(self) -> Condition:
        set_fields = [f for f in ("all_of", "any_of", "not_", "incident", "tool_called", "plc", "memory_contains") if getattr(self, f) is not None]
        if len(set_fields) != 1:
            raise ValueError(f"a condition needs exactly one of all_of/any_of/not/incident/tool_called/plc/memory_contains, got {set_fields}")
        if (self.with_args is not None or self.args_contains is not None) and self.tool_called is None:
            raise ValueError("with_args/args_contains only apply to tool_called")
        return self

    def evaluate(self, world: World) -> bool:
        if self.all_of is not None:
            return all(c.evaluate(world) for c in self.all_of)
        if self.any_of is not None:
            return any(c.evaluate(world) for c in self.any_of)
        if self.not_ is not None:
            return not self.not_.evaluate(world)
        if self.incident is not None:
            return self.incident in world.incidents
        if self.tool_called is not None:
            return any(
                call["tool"] == self.tool_called and self._args_match(call.get("args") or {})
                for call in world.tool_calls
            )
        if self.plc is not None:
            return all(self._plc_match(tag, test, world) for tag, test in self.plc.items())
        if self.memory_contains is not None:
            needle = self.memory_contains.lower()
            return any(needle in content.lower() for content in world.memory)
        return False

    def _args_match(self, args: dict) -> bool:
        if self.with_args and not all(str(args.get(k)).lower() == str(v).lower() for k, v in self.with_args.items()):
            return False
        return not (self.args_contains and self.args_contains.lower() not in str(args).lower())

    def _plc_match(self, tag: str, test: dict[str, float], world: World) -> bool:
        if tag not in world.plc:
            return False
        return all(COMPARATORS[op](world.plc[tag], value) for op, value in test.items())


class Setup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    difficulty: Literal["easy", "medium", "hard"] = "easy"
    seed: int = 0
    notes: str = ""
    defended: bool = False  # start with SafeEnvelope on (the defended variant of the challenge)


class Challenge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[A-Za-z0-9_]+$")
    title: str
    owasp_asi: ASI
    difficulty: Literal["intro", "easy", "medium", "hard"]
    story: str
    objective: str
    setup: Setup = Setup()
    success_condition: Condition
    hints: list[str] = Field(min_length=1, max_length=3)
    mitigation: str


def load_challenges(root: str | Path) -> dict[str, Challenge]:
    """Load every challenges/<id>/challenge.yaml, keyed by id. Fails loudly on a bad file."""
    challenges: dict[str, Challenge] = {}
    for path in sorted(Path(root).glob("*/challenge.yaml")):
        challenge = Challenge.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        if challenge.id != path.parent.name:
            raise ValueError(f"{path}: id {challenge.id!r} does not match its folder {path.parent.name!r}")
        if challenge.id in challenges:
            raise ValueError(f"duplicate challenge id {challenge.id!r}")
        challenges[challenge.id] = challenge
    return challenges
