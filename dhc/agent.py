"""The in-code agent surface.

This module owns :class:`Agent` — the object action blocks see as ``agent`` —
and :class:`AgentHandle`, the lightweight task handle a parent holds for
await/poll/cancel/status/result.

The runtime delivers this surface into each agent's REPL namespace; agent code
never touches the runtime directly. All collaborators (runtime, artifact
store, event bus) are injected by the runtime — this module imports no sibling
modules at module level (constructor injection only).
"""

from __future__ import annotations

import subprocess
import time
from typing import Any, Callable, Optional

from .models import (
    AgentStatus,
    Artifact,
    Result,
    ToolOutput,
    is_terminal,
)


class ToolResult(ToolOutput):
    """A :class:`~dhc.models.ToolOutput` tagged with success/failure.

    ``models.ToolOutput`` is kept intact; this subclass adds the ``ok`` flag
    so a failed tool call is *indistinguishable in shape* from a success
    (INFO-020) while still carrying the error text.
    """

    ok: bool = True


def _tool_output(callable: Callable[..., Any], *args: Any, **kwargs: Any) -> ToolResult:
    """Run *callable*, capturing its output as a :class:`ToolResult`.

    Exceptions are captured as ``ok=False`` with the error text — a tool
    failure is a value, not a transport break.
    """
    try:
        text = callable(*args, **kwargs)
        return ToolResult(text=str(text), ok=True)
    except Exception as exc:  # noqa: BLE001 - capture any tool failure
        return ToolResult(text=f"{type(exc).__name__}: {exc}", ok=False)


def bash(cmd: str, timeout: float = 30.0) -> str:
    """A simple subprocess wrapper returning the captured output as text."""
    try:
        proc = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return f"TimeoutError: command timed out after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    out = proc.stdout or ""
    if proc.returncode != 0:
        err = proc.stderr or ""
        return f"exit {proc.returncode}\n{out}\n{err}".strip()
    return out


# --------------------------------------------------------------------------- #
# In-memory room registry (standalone default; the real communication module
# is wired by the integration agent later).
# --------------------------------------------------------------------------- #


class _Room:
    """Minimal in-memory room: a name plus member ids."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.members: list[str] = []


_ROOMS: dict[str, _Room] = {}


def room(agent: "Agent", name: str) -> _Room:
    """Return the shared room *name*, registering *agent* as a member."""
    r = _ROOMS.setdefault(name, _Room(name))
    if agent.id not in r.members:
        r.members.append(agent.id)
    return r


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #


class Agent:
    """The runtime agent — the in-code surface action blocks call.

    This is *not* the frozen sketch dataclass from the mockups: it is a live
    object whose methods delegate to the runtime that owns it. The runtime
    builds one per spawned agent and injects it into the agent's REPL
    namespace as ``agent``.
    """

    def __init__(
        self,
        id: str,
        requirement: str,
        acceptance: tuple = (),
        parent_id: Optional[str] = None,
        runtime: Any = None,
        artifact_store: Any = None,
        created_ts: Optional[float] = None,
    ) -> None:
        self.id = id
        self.requirement = requirement
        self.acceptance = tuple(acceptance)
        self.parent_id = parent_id
        # Lifecycle state. Stored as ``_status`` because ``status()`` is a
        # required callable method of the in-code surface (contract §1); the
        # brief's ``status`` field is realized here to keep the method.
        self._status: AgentStatus = AgentStatus.pending
        # The settled result. Stored as ``_result`` because ``result()`` is a
        # required callable method of the in-code surface (contract §1); the
        # brief's ``result`` field is realized here to keep the method.
        self._result: Optional[Result] = None
        self.children: list[str] = []
        self.created_ts: float = created_ts if created_ts is not None else time.time()
        self.settled_ts: Optional[float] = None
        # The most recent result produced by a turn (complete/fail/cancel).
        # Runtime-owned: reset before each turn, read after it.
        self._last_result: Optional[Result] = None
        # Runtime-owned collaborators (injected; duck-typed).
        self._runtime = runtime
        self._artifact_store = artifact_store

    # -- identity / lifecycle ------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Agent(id={self.id!r}, status={self.status.value!r})"

    @property
    def done(self) -> bool:
        """True once the agent has settled (reached a terminal state)."""
        return self._result is not None and is_terminal(self._status)

    # -- delegation ----------------------------------------------------------

    def spawn(
        self,
        requirement: str,
        acceptance: tuple = (),
        on_done: Optional[Callable[[Any], None]] = None,
        **kwargs: Any,
    ) -> "Agent":
        """Spawn a child agent (non-blocking) and return its handle.

        *on_done* is registered as a completion callback on the parent's
        stream: it runs once, when the child settles — success or failure
        alike (INFO-033). Extra keyword arguments (driver, namespace, ...)
        are forwarded to the runtime.
        """
        if self._runtime is None:
            raise RuntimeError("agent is not attached to a runtime")
        child = self._runtime.spawn(
            requirement=requirement,
            acceptance=acceptance,
            parent_id=self.id,
            on_done=on_done,
            _agent_callback=True,
            **kwargs,
        )
        # Runtime.spawn already registered the child on this agent's children
        # list (parent_id was passed); do not append again.
        return child.get()

    # -- artifacts -----------------------------------------------------------

    def publish(self, headline: str, summary: str, report: Any) -> Artifact:
        """Persist a finding and return its content-addressed artifact."""
        if self._artifact_store is None:
            raise RuntimeError("agent has no artifact store")
        return self._artifact_store.publish(headline, summary, report)

    # -- results -------------------------------------------------------------

    def complete(self, headline: str, artifacts: tuple = ()) -> Result:
        """Settle this agent as completed with *headline* as the value."""
        result = Result(done=True, ok=True, value=headline, artifacts=list(artifacts))
        self._last_result = result
        return result

    def fail(self, reason: str) -> Result:
        """Settle this agent as failed with *reason*."""
        result = Result(done=True, ok=False, reason=reason)
        self._last_result = result
        return result

    def cancel(self, reason: str = "cancelled") -> Result:
        """Settle this agent as cancelled with *reason*."""
        result = Result(done=True, ok=False, reason=reason)
        self._last_result = result
        return result

    def status(self) -> Result:
        """Return the current lifecycle state as a Result envelope."""
        return Result(done=self.done, ok=self._status == AgentStatus.completed)

    def result(self) -> Result:
        """Return the settled result, or a not-done envelope if unsettled."""
        if self._result is not None:
            return self._result
        return Result(done=False, ok=False, reason="not settled")

    def tool(self, callable: Callable[..., Any], *args: Any, **kwargs: Any) -> ToolResult:
        """Run *callable*, capturing its output as a :class:`ToolResult`."""
        return _tool_output(callable, *args, **kwargs)

    # -- supervision (delegate to the runtime) -------------------------------

    def await_(self, child: "AgentHandle") -> Any:
        """Ensure-terminal: block until *child* settles, return its Completion."""
        if self._runtime is None:
            raise RuntimeError("agent is not attached to a runtime")
        return self._runtime.await_(child.id)

    def poll(self, child: "AgentHandle") -> AgentStatus:
        """Non-blocking: return *child*'s current lifecycle state."""
        if self._runtime is None:
            raise RuntimeError("agent is not attached to a runtime")
        return self._runtime.poll(child.id)

    def children_of(self, child: "AgentHandle") -> list:
        """Return the ids of *child*'s own children."""
        if self._runtime is None:
            raise RuntimeError("agent is not attached to a runtime")
        return self._runtime.children_of(child.id)


# --------------------------------------------------------------------------- #
# AgentHandle
# --------------------------------------------------------------------------- #


class AgentHandle:
    """Lightweight task handle a parent holds for await/poll/cancel/status.

    Carries the child's id plus a reference to the runtime; all operations
    delegate to the runtime. The handle is *not* the agent: it exposes no
    REPL surface and cannot mutate the child.
    """

    def __init__(self, agent_id: str, runtime: Any) -> None:
        self.id = agent_id
        self._runtime = runtime

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"AgentHandle(id={self.id!r})"

    def await_(self) -> Any:
        """Ensure-terminal: block until the agent settles, return its Completion."""
        return self._runtime.await_(self.id)

    def poll(self) -> AgentStatus:
        """Non-blocking: return the agent's current lifecycle state."""
        return self._runtime.poll(self.id)

    def cancel(self, reason: str = "cancelled") -> Result:
        """Cancel the agent's worker; it settles as cancelled."""
        return self._runtime.cancel(self.id, reason=reason)

    def status(self) -> AgentStatus:
        """Return the agent's current lifecycle state."""
        return self._runtime.status(self.id)

    def result(self) -> Result:
        """Return the agent's settled result."""
        return self._runtime.result(self.id)

    def get(self) -> Agent:
        """Return the underlying Agent object."""
        return self._runtime.get(self.id)