"""Core data models for dhc.

These mirror the shapes sketched in
``breakdown/02-architecture/pre-studies/mockups/_support.py`` and extend them
per the use-cases: progressive-disclosure artifacts, terminal agent states,
at-most-once completions, and room messaging.

All models are pydantic v2 value objects. Immutable models are frozen; mutable
ones (``Room``) are not.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..errors import ChannelError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _content_id(content: str) -> str:
    """Content address: ``sha256:<hex>`` of the canonical content bytes."""
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _new_id() -> str:
    return uuid.uuid4().hex


# --------------------------------------------------------------------------- #
# Enums
# --------------------------------------------------------------------------- #


class EventKind(str, Enum):
    """Kinds of events an agent can emit or observe."""

    turn_started = "turn_started"
    turn_completed = "turn_completed"
    turn_failed = "turn_failed"
    artifact_published = "artifact_published"
    child_spawned = "child_spawned"
    child_settled = "child_settled"
    message_sent = "message_sent"
    room_message = "room_message"
    escalation = "escalation"
    cancelled = "cancelled"
    timeout = "timeout"
    crash = "crash"
    operator_question = "operator_question"
    operator_answer = "operator_answer"


class AgentStatus(str, Enum):
    """Lifecycle state of an agent."""

    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"
    timeout = "timeout"


#: The settled, terminal states of an agent lifecycle.
TERMINAL_STATES: frozenset[AgentStatus] = frozenset(
    {
        AgentStatus.completed,
        AgentStatus.failed,
        AgentStatus.cancelled,
        AgentStatus.timeout,
    }
)

#: Type alias for the terminal states (for annotations).
TerminalState = Literal["completed", "failed", "cancelled", "timeout"]


def is_terminal(status: AgentStatus) -> bool:
    """True when *status* is a settled terminal state."""
    return status in TERMINAL_STATES


# --------------------------------------------------------------------------- #
# Artifact
# --------------------------------------------------------------------------- #


class Artifact(BaseModel):
    """An immutable, content-addressed finding.

    Progressive-disclosure tiers: ``headline`` -> ``summary`` -> ``report``.
    The ``id`` is the sha256 content address of the full body (see
    :meth:`content`); it is computed on construction and validated when given.
    """

    model_config = ConfigDict(frozen=True)

    id: str = ""
    headline: str
    summary: str
    report: Any

    @model_validator(mode="after")
    def _content_address(self) -> "Artifact":
        computed = _content_id(self.content())
        if self.id and self.id != computed:
            raise ValueError(
                f"Artifact id {self.id!r} does not match content hash {computed!r}"
            )
        object.__setattr__(self, "id", computed)
        return self

    def content(self) -> str:
        """Return the full body of the artifact as text."""
        if isinstance(self.report, str):
            return self.report
        if isinstance(self.report, bytes):
            return self.report.decode("utf-8", errors="replace")
        return json.dumps(self.report, ensure_ascii=False, sort_keys=True, default=str)


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #


class Result(BaseModel):
    """Outcome of a coded action.

    ``artifacts`` holds artifact *ids* (by reference), never full bodies.
    """

    model_config = ConfigDict(frozen=True)

    done: bool
    ok: bool
    value: Any = None
    reason: str = ""
    artifacts: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Event
# --------------------------------------------------------------------------- #


class Event(BaseModel):
    """One recorded occurrence in an agent's lifecycle.

    ``payload`` is by reference: artifact ids / child ids, never full bodies.
    """

    model_config = ConfigDict(frozen=True)

    kind: EventKind
    causal_id: str | None = None
    agent_id: str
    payload: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------- #
# Completion
# --------------------------------------------------------------------------- #


class Completion(BaseModel):
    """One settled child = one completion, at most once.

    ``status`` must be terminal (see :func:`is_terminal`). At-most-once
    settlement is enforced by :class:`CompletionLog`.
    """

    model_config = ConfigDict(frozen=True)

    agent_id: str
    status: AgentStatus
    summary: str = ""
    artifact_ids: list[str] = Field(default_factory=list)
    reason: str = ""

    @model_validator(mode="after")
    def _terminal_status(self) -> "Completion":
        if not is_terminal(self.status):
            raise ValueError(
                f"Completion status must be terminal, got {self.status!r}"
            )
        return self


class CompletionLog:
    """At-most-once settlement registry: one completion per agent id.

    The first settlement for an agent id wins; later attempts raise
    :class:`~dhc.errors.ChannelError`.
    """

    def __init__(self) -> None:
        self._settled: dict[str, Completion] = {}

    def settle(self, completion: Completion) -> Completion:
        if completion.agent_id in self._settled:
            raise ChannelError(
                f"agent {completion.agent_id!r} already settled; "
                "at most one completion per agent"
            )
        self._settled[completion.agent_id] = completion
        return completion

    def get(self, agent_id: str) -> Completion | None:
        return self._settled.get(agent_id)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._settled

    def __len__(self) -> int:
        return len(self._settled)


# --------------------------------------------------------------------------- #
# ToolOutput
# --------------------------------------------------------------------------- #


class ToolOutput(BaseModel):
    """Captured output of a tool call.

    Mirrors ``_support.py``: the mockups read against ``text`` plus the
    ``search``/``read`` pagination helpers.
    """

    model_config = ConfigDict(frozen=True)

    text: str
    id: str = Field(default_factory=_new_id)

    @classmethod
    def minted(cls, text: str) -> "ToolOutput":
        return cls(text=text)

    def search(self, pattern: str, limit: int = 5) -> list[tuple[int, str]]:
        """Return (1-based line number, line) hits containing *pattern*."""
        hits = [
            (n, line)
            for n, line in enumerate(self.text.splitlines(), 1)
            if pattern in line
        ]
        return hits[:limit]

    def read(self, size: int = 4_000, offset: int = 0) -> str:
        """Return a size-capped slice of the captured text."""
        return self.text[offset : offset + size]


# --------------------------------------------------------------------------- #
# Messaging
# --------------------------------------------------------------------------- #


class Message(BaseModel):
    """A point-to-point message between two agents."""

    model_config = ConfigDict(frozen=True)

    sender_id: str
    recipient_id: str
    body: str
    ts: datetime = Field(default_factory=_utcnow)


class Room(BaseModel):
    """A shared meeting space: every posted message is visible to all members."""

    name: str
    member_ids: list[str] = Field(default_factory=list)
    messages: list[Message] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Turn
# --------------------------------------------------------------------------- #


class Turn(BaseModel):
    """A coded action submitted for execution against an agent's REPL."""

    model_config = ConfigDict(frozen=True)

    code: str
    agent_id: str
    ts: datetime = Field(default_factory=_utcnow)