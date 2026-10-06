"""The shapes the scenario mockups read against — sketches, not the surface:
trivial bodies are deliberate, the shape is the annotation. What each sketch
must show, with citations, lives in requirements.md.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


def _content_id(*parts: str) -> str:
    return hashlib.sha1("\x00".join(parts).encode()).hexdigest()[:8]


def _agent_id() -> str:
    return uuid.uuid4().hex[:8]


@dataclass(frozen=True)
class Artifact:
    id: str
    headline: str
    summary: str
    report: object


@dataclass(frozen=True)
class Result(Generic[T]):
    done: bool
    ok: bool
    value: T | None = None
    reason: str = ""
    artifacts: tuple = ()


@dataclass(frozen=True)
class Event(Result):
    child: Agent | None = None


class EventStream:
    def register(self, callback) -> None:
        return None


@dataclass(frozen=True)
class ToolOutput:
    text: str
    id: str

    @classmethod
    def minted(cls, text: str) -> "ToolOutput":
        return cls(text=text, id=_content_id("out", text))

    def search(self, pattern: str, limit: int = 5) -> list[tuple[int, str]]:
        hits = [(n, line) for n, line in enumerate(self.text.splitlines(), 1)
                if pattern in line]
        return hits[:limit]

    def read(self, size: int = 4_000, offset: int = 0) -> str:
        return self.text[offset:offset + size]


@dataclass(frozen=True)
class Agent:
    requirement: str
    acceptance: tuple
    channels: tuple = ()
    children: tuple = ()
    events: EventStream = field(default_factory=EventStream)
    id: str = field(default_factory=_agent_id)

    def tool(self, callable, *args, **kwargs) -> ToolOutput:
        return ToolOutput.minted(callable(*args, **kwargs))

    def publish(self, headline: str, summary: str, report) -> Artifact:
        return Artifact(id=_content_id("art", headline, summary),
                        headline=headline, summary=summary, report=report)

    def fail(self, reason: str) -> Result[T]:
        return Result(done=True, ok=False, reason=reason)

    def complete(self, headline: str, artifacts=()) -> Result[T]:
        return Result(done=True, ok=True, value=headline, artifacts=tuple(artifacts))

    @property
    def done(self) -> bool:
        return False

    def status(self) -> Result[T]:
        return Result(done=self.done, ok=False)

    def result(self) -> Result[T]:
        return self.fail("sketch")

    def cancel(self, reason: str) -> Result[T]:
        return self.fail(reason)

    def spawn(self: Agent, requirement: str, acceptance: tuple = (),
              on_done: Callable[[Event], None] | None = None) -> Agent:
        child = Agent(requirement=requirement, acceptance=acceptance)
        if on_done is not None:
            child.events.register(on_done)
        return child


def bash(cmd: str) -> str:
    tid = cmd.split()[-1]
    return (f"================= {tid} =================\n"
            "1 passed in 0.02s\n\n"
            "warnings summary:\n"
            "hello_turn.py::turn_hello\n"
            "  a fabricated deprecation warning, padded long enough that the\n"
            "  size-capped tail read lands inside the warnings summary — the\n"
            "  pagination gesture reads something\n"
            "  40 warnings in 0.31s\n"
            "1 warning in 0.31s\n")
