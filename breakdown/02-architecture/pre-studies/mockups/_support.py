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
import uuid
from dataclasses import dataclass, field
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


def _content_id(*parts: str) -> str:
    """Content-addressed handle — git-style sha1, not security."""
    return hashlib.sha1("\x00".join(parts).encode()).hexdigest()[:8]


def _agent_id() -> str:
    """Static per-agent id — uuid, not content: agents are execution, not
    content — identical requirements are distinct agents. Unique across
    REPLs, thread or process (INFO-038): OS entropy, no counter to lock."""
    return uuid.uuid4().hex[:8]


@dataclass(frozen=True)
class Artifact:
    """One published finding — headline/summary/report tiers (INFO-006)."""
    id: str
    headline: str
    summary: str
    report: object          # the verdict itself rides in the report tier


@dataclass(frozen=True)
class Status(Generic[T]):
    """The one shape, peek to terminal — `done` is the poll's predicate
    (INFO-043); the settled payload rides behind it (INFO-031), uniform
    across verbs and contexts: the context's own in `value`, provenance in
    `artifacts`. Until `done`, the payload fields stay empty."""
    done: bool
    ok: bool
    value: T | None = None  # the context's own — headline, tally, verdict
    reason: str = ""
    artifacts: tuple = ()   # provenance pairs, by reference (INFO-027, unpinned)


@dataclass(frozen=True)
class Event(Status):
    """One arrived event — a settled Status tagged with its child (INFO-039):
    the stream's only intake type — only a Status enters (INFO-045)."""
    child: Agent | None = None    # who the event is about — the callback's payload


class EventStream:
    """One agent's event stream — the channel completions ride (INFO-046).

    Intake is typed to the terminal: only a Status enters (INFO-045). The
    general event loop polls it outside run_code — the REPL never polls or
    drains it (INFO-045); the queue is runtime mechanics and stays a comment."""

    def register(self, callback) -> None:
        """Registration by held handle (INFO-045): an agent registers its own
        stream, a child's via its spawn handle, a peer's only via a wired
        channel (INFO-018). The callback runs in the registrant's REPL
        between its own actions, never concurrently (INFO-033)."""
        return None    # sketch: the shape is the annotation


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
    requirement: str
    acceptance: tuple       # the parent's criteria
    channels: tuple = ()
    children: tuple = ()    # the previous turn's spawn handles, REPL-bound (INFO-030)
    events: EventStream = field(default_factory=EventStream)
                             # the agent's stream — one channel (INFO-045),
                             # polled by the general event loop, never the REPL
    id: str = field(default_factory=_agent_id)
                             # static per agent — minted once at birth, frozen
                             # with the handle; never derived, never recomputed

    def tool(self, callable, *args, **kwargs) -> ToolOutput:
        """One sync tool call — the ONE at the boundary."""
        return ToolOutput.minted(callable(*args, **kwargs))

    def publish(self, headline: str, summary: str, report) -> Artifact:
        """Mint content-addressed; the store itself is runtime mechanics."""
        return Artifact(id=_content_id("art", headline, summary),
                        headline=headline, summary=summary, report=report)

    def fail(self, reason: str) -> Status[T]:
        """Failure = success shape."""
        return Status(done=True, ok=False, reason=reason)

    def complete(self, headline: str, artifacts=()) -> Status[T]:
        return Status(done=True, ok=True, value=headline, artifacts=tuple(artifacts))

    # — child handles: the children are Agents too (INFO-043) —

    @property
    def done(self) -> bool:
        """The poll predicate (INFO-043) — attribute read vs method, unpinned."""
        return False    # sketch: the shape is the annotation

    def status(self) -> Status[T]:
        """Sync, non-blocking peek (INFO-043) — the terminal's own shape,
        payload still empty."""
        return Status(done=self.done, ok=False)    # sketch: never settles ok

    def result(self) -> Status[T]:
        """Await/settle — settles at once in the sketch (INFO-031)."""
        return self.fail("sketch")    # the shape is the return type

    def cancel(self, reason: str) -> Status[T]:
        """INFO-034 — the cancelled result is typed like any other."""
        return self.fail(reason)     # one shape, success or failure (INFO-011)

    def spawn(self: Agent, requirement: str, acceptance: tuple = (),
              on_done: Callable[[Event], None] | None = None) -> Agent:
        """INFO-029 — the free verb takes the value acted on first: the parent.
        Children are Agents too (INFO-043): the handle members ride Agent.
        The optional completion hook (INFO-033): spawn-time registration on
        the child's stream — one callback serves success and failure, receives
        the settled Event, and runs between this parent's own actions, never
        concurrently (INFO-039)."""
        child = Agent(requirement=requirement, acceptance=acceptance)
        if on_done is not None:
            child.events.register(on_done)    # the stream's one intake — the
                                              # same register as handle-side
                                              # (INFO-045)
        return child


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
