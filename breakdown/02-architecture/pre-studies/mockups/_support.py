"""Complement to the scenario mockups — the shapes the turns read against.

Sketches, not the surface: the injected `self` (INFO-029 draft) — the
parent's `children` and the child handles — the result-side `ToolOutput`,
plus the typed terminals `fail`/`complete` share and the free `spawn`.
The checks are the blocks' own — authored in-block per criterion (INFO-003):
the check is the branch, the reason is the block's formatted string. Runtime
mechanics stay comments, per INFO-042 — persist-before-execute, the boundary
log, and the artifact store are the harness's, not sketched here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Generic, TypeVar

T = TypeVar("T")


def _content_id(*parts: str) -> str:
    """Content-addressed handle — git-style sha1, not security."""
    return hashlib.sha1("\x00".join(parts).encode()).hexdigest()[:8]


@dataclass(frozen=True)
class Artifact:
    """One published finding — headline/summary/report tiers (INFO-006)."""
    id: str
    headline: str
    summary: str
    report: object          # the verdict itself rides in the report tier


@dataclass(frozen=True)
class Result(Generic[T]):
    """Generic terminal — ok/value/reason, uniform across verbs and contexts:
the context's own payload rides `value`; provenance rides `artifacts`."""
    ok: bool
    value: T | None = None  # the context's own — headline, tally, verdict
    reason: str = ""
    artifacts: tuple = ()   # provenance pairs, by reference (INFO-027, unpinned)


@dataclass(frozen=True)
class Status:
    """Non-blocking peek — the poll's predicate (INFO-043)."""
    done: bool
    ok: bool


@dataclass(frozen=True)
class Event(Result):
    """One arrived event — a settled Result tagged with its child (INFO-039)."""
    child: Agent | None = None    # who the event is about — the drain path


@dataclass(frozen=True)
class ToolOutput:
    """result-side surface: the full output persisted as an artifact, a handle back."""
    text: str
    id: str                 # content-addressed; by-reference open form (INFO-027)

    @classmethod
    def minted(cls, text: str) -> "ToolOutput":
        return cls(text=text, id=_content_id("out", text))

    def search(self, pattern: str, limit: int = 5) -> list[tuple[int, str]]:
        """Ranked hits — order of appearance stands in for rank."""
        hits = [(n, line) for n, line in enumerate(self.text.splitlines(), 1)
                if pattern in line]
        return hits[:limit]

    def read(self, size: int = 4_000, offset: int = 0) -> str:
        """Size-capped pull of the report tier."""
        return self.text[offset:size]


@dataclass(frozen=True)
class Agent:
    """The injected read-only context (INFO-029 draft) + verb dispatch stubs.

    The verbs stay free functions in the library; these attribute stubs only
    mark the boundary — `tool` is CALL-shaped, the boundary log is runtime
    mechanics and stays a comment (INFO-042).
    """
    id: str
    requirement: str
    acceptance: tuple       # the parent's criteria
    channels: tuple = ()
    children: tuple = ()    # the previous turn's spawn handles, REPL-bound (INFO-030)

    def tool(self, callable, *args, **kwargs) -> ToolOutput:
        """One sync tool call — the ONE at the boundary."""
        return ToolOutput.minted(callable(*args, **kwargs))

    def publish(self, headline: str, summary: str, report) -> Artifact:
        """Mint content-addressed; the store itself is runtime mechanics."""
        return Artifact(id=_content_id("art", headline, summary),
                        headline=headline, summary=summary, report=report)

    def fail(self, reason: str) -> Result[T]:
        """Failure = success shape."""
        return Result(ok=False, reason=reason)

    def complete(self, headline: str, artifacts=()) -> Result[T]:
        return Result(ok=True, value=headline, artifacts=tuple(artifacts))

    # — child handles: the children are Agents too (INFO-043) —

    @property
    def done(self) -> bool:
        """The poll predicate (INFO-043) — attribute read vs method, unpinned."""
        return False    # sketch: the shape is the annotation

    def status(self) -> Status:
        """Sync, non-blocking peek (INFO-043)."""
        return Status(done=self.done, ok=False)    # sketch: never settles ok

    def result(self) -> Result[T]:
        """Await/settle — settles at once in the sketch (INFO-031)."""
        return self.fail("sketch")    # the shape is the return type

    def cancel(self, reason: str) -> Result[T]:
        """INFO-034 — the cancelled result is typed like any other."""
        return self.fail(reason)     # one shape, success or failure (INFO-011)

    def drain(self) -> tuple:
        """Arrived events, completion order (INFO-039) — method or fn, unpinned."""
        return ()                    # sketch: the shape is the annotation


Worker = Agent    # spec value, not a built-in (INFO-007) — children are Agents too


def spawn(parent: Agent, spec: type, requirement: str,
          acceptance: tuple = ()) -> Agent:
    """INFO-029 — the free verb takes the value acted on first: the parent.
    Children are Agents too (INFO-043): the handle members ride Agent."""
    return Agent(id=_content_id("agent", parent.id, requirement),
                 requirement=requirement, acceptance=acceptance)


def bash(cmd: str) -> str:
    """Stand-in for `dhc.tools.bash` — fabricates the run's pytest tail.

    Long enough that the size-capped tail read lands inside the warnings
    summary — the pagination gesture reads something.
    """
    tid = cmd.split()[-1]
    return (f"================= {tid} =================\n"
            "1 passed in 0.02s\n\n"
            "warnings summary:\n"
            "hello_turn.py::turn_hello\n"
            "  the boundary log is runtime mechanics — persist-before-execute,\n"
            "  the artifact store, and the boundary log itself stay comments\n"
            "  (INFO-042); the persisted block executes against the persistent\n"
            "  REPL after this pull\n"
            "  40 warnings in 0.31s\n"
            "1 warning in 0.31s\n")
