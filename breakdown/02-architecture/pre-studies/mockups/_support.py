"""Complement to the scenario mockups — the shapes the turns read against.

Sketches, not the surface: the injected `self` (INFO-029 draft) and the
result-side `ToolOutput`, plus the typed terminals `fail`/`complete` share.
The checks are the blocks' own — authored in-block per criterion (INFO-003):
the check is the branch, the reason is the block's formatted string. Runtime
mechanics stay comments, per INFO-042 — persist-before-execute, the boundary
log, and the artifact store are the harness's, not sketched here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass


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
class Result:
    """Typed terminal — `fail`'s shape uniform with `complete`'s."""
    ok: bool
    headline: str = ""
    reason: str = ""
    artifacts: tuple = ()   # provenance pairs, by reference (INFO-027, unpinned)


@dataclass(frozen=True)
class ToolOutput:
    """Result-side surface: the full output persisted as an artifact, a handle back."""
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

    def read(self, size: int = 4_000, offset=0) -> str:
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

    def tool(self, callable, *args, **kwargs) -> ToolOutput:
        """One sync tool call — the ONE at the boundary."""
        return ToolOutput.minted(callable(*args, **kwargs))

    def publish(self, headline: str, summary: str, report) -> Artifact:
        """Mint content-addressed; the store itself is runtime mechanics."""
        return Artifact(id=_content_id("art", headline, summary),
                        headline=headline, summary=summary, report=report)

    def fail(self, reason: str) -> Turn:
        """Failure = success shape."""
        return Result(ok=False, reason=reason)

    def complete(self, headline: str, artifacts=()) -> Turn:
        return Result(ok=True, headline=headline, artifacts=tuple(artifacts))


def bash(cmd: str) -> str:
    """Stand-in for `dhc.tools.bash` — fabricates the run's pytest tail.

    Long enough that the tail-read at offset 300 lands inside the warnings
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
