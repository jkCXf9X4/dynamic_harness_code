"""The in-code agent surface.

This module owns the three faces of the agent at the framework↔REPL
boundary:

* :class:`Agent` — the framework-side object. The pump, the settle path,
  and the driver seam (INFO-051 — the driver is runtime machinery) use it.
* :class:`WorkspaceAgent` — the facade action blocks see as ``agent``. The
  runtime delivers this into each agent's REPL namespace, never the raw
  Agent. Its public surface is the declared :data:`AGENT_SURFACE`, pinned by
  the boundary tests (``tests/framework/test_repl_boundary.py``).
* :class:`AgentHandle` — the lightweight task handle a parent holds for
  await/poll/cancel/status/result. ``spawn`` returns this, never a raw
  child; there is deliberately no ``get()`` unwrap — the raw Agent is
  reachable only framework-side via ``Runtime.get``.

The boundary is a *declared-surface* contract, not a sandbox: blocks run
arbitrary Python and can still import modules or introspect closures. What
the contract buys is that agent-authored code has nothing to accidentally
rely on beyond the declared surface — no ``_runtime``, no writable
``_status``, no shared mutable ``children`` — so the surface cannot silently
grow and the gates (at-most-once settlement, crash containment) stay
framework-owned.

Deliberate crossings, by design and out of this contract's scope: ``bash``
and import rights (CodeAct), ``state["_driver"]`` (the brain-swap seam),
and the driver receiving the raw Agent (INFO-051).

The only collaborator is the runtime itself, injected by the constructor —
this module imports no sibling modules at module level. Artifact
publication is a composed namespace tool (``dhc.tooling``), not an agent
method (decision 0014). Direct messaging is the one communication
primitive on the agent itself: :meth:`Agent.send` delegates to
``Runtime.send`` (decision 0015); channel policies are tooling.
"""

from __future__ import annotations

import difflib
import os
import signal
import subprocess
import time
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from ..data.models import (
    AgentStatus,
    Result,
    ToolOutput,
    is_terminal,
)

# The only keyword pass-throughs accepted by Agent.spawn (W3.9). Anything
# else is a caller typo and must fail loudly with a did-you-mean hint.
_SPAWN_PASS_THROUGH = frozenset({"driver", "namespace"})


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
    """Run *cmd* in a new process group, returning the captured output.

    The command is a session leader (``start_new_session=True``) so the
    whole tree it spawns can be killed with ``SIGKILL`` — on timeout, on a
    cancel request, or on any wait error. Polling a cancel predicate (bound
    by the REPL engine to the runtime stop flag) means a running turn's
    blocking external call dies at the next boundary instead of orphaning
    its children and running to the step timeout.
    """
    # Imported lazily: the engine hook is only needed while a turn runs.
    from .repl import cancel_requested

    try:
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    deadline = time.monotonic() + timeout
    out = err = ""
    while True:
        cancelled = cancel_requested()
        remaining = deadline - time.monotonic()
        if cancelled or remaining <= 0:
            _kill_process_group(proc)
            try:
                proc.communicate(timeout=1.0)
            except Exception:  # noqa: BLE001 - pipes closed under the kill
                pass
            if cancelled:
                return "CancelledError: command cancelled"
            return f"TimeoutError: command timed out after {timeout}s"
        try:
            # Short slices: repeated communicate() calls keep already-read
            # output, so polling loses nothing and cannot deadlock on a full
            # pipe buffer.
            out, err = proc.communicate(timeout=min(0.05, remaining))
            break
        except subprocess.TimeoutExpired:
            continue
        except Exception as exc:  # noqa: BLE001
            _kill_process_group(proc)
            return f"{type(exc).__name__}: {exc}"
    out = out or ""
    if proc.returncode != 0:
        err = err or ""
        return f"exit {proc.returncode}\n{out}\n{err}".strip()
    return out


def _kill_process_group(proc: "subprocess.Popen") -> None:
    """SIGKILL *proc*'s whole process group (fall back to the process)."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except Exception:  # noqa: BLE001 - already gone
            pass


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
        # Runtime-owned collaborator (injected; duck-typed).
        self._runtime = runtime
        # Token/cost accumulators (IMP-004). Written only by
        # ``record_usage`` — the single accumulation point, called from the
        # driver seam; read by the state view-model (``build_agent_tree``).
        # The mock path never calls ``record_usage``, so these stay zero.
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._cached_tokens = 0
        self._cost_usd = 0.0

    # -- identity / lifecycle ------------------------------------------------

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"Agent(id={self.id!r}, status={self.status.value!r})"

    @property
    def done(self) -> bool:
        """True once the agent has settled (reached a terminal state)."""
        return self._result is not None and is_terminal(self._status)

    # -- token/cost accounting (IMP-004) ------------------------------------

    def record_usage(self, usage: Optional[dict], cost_usd: Optional[float]) -> None:
        """Accumulate one provider response's usage onto this agent.

        The ONE accumulation point: called only from the driver seam
        (``LLMDriver.__call__``) with the client's last response usage.
        None-safe — a ``None`` usage or missing keys contribute nothing, so
        a usage-less provider call (or the mock path) leaves the counters
        unchanged rather than crashing or fabricating a number.
        """
        if usage:
            self._prompt_tokens += int(usage.get("prompt_tokens", 0) or 0)
            self._completion_tokens += int(usage.get("completion_tokens", 0) or 0)
            self._cached_tokens += int(usage.get("cached_tokens", 0) or 0)
        if cost_usd is not None:
            self._cost_usd += float(cost_usd)

    @property
    def prompt_tokens(self) -> int:
        """Total prompt tokens across this agent's provider calls."""
        return self._prompt_tokens

    @property
    def completion_tokens(self) -> int:
        """Total completion tokens across this agent's provider calls."""
        return self._completion_tokens

    @property
    def cached_tokens(self) -> int:
        """Total prompt-cache tokens across this agent's provider calls."""
        return self._cached_tokens

    @property
    def tokens(self) -> int:
        """Total tokens (prompt + completion) across this agent's calls."""
        return self._prompt_tokens + self._completion_tokens

    @property
    def cost_usd(self) -> float:
        """Running USD estimate across this agent's provider calls."""
        return self._cost_usd

    # -- delegation ----------------------------------------------------------

    def spawn(
        self,
        requirement: str,
        acceptance: tuple = (),
        on_done: Optional[Callable[[Any], None]] = None,
        **kwargs: Any,
    ) -> "AgentHandle":
        """Spawn a child agent (non-blocking) and return its handle.

        *on_done* is registered as a completion callback on the parent's
        stream: it runs once, when the child settles — success or failure
        alike (INFO-033). The only accepted keyword pass-throughs are
        *driver* and *namespace*; any other keyword raises ``TypeError``
        with a did-you-mean suggestion (W3.9 — a typo like
        ``namespce=`` must fail loudly, not be swallowed).

        The handle is the join surface (await/poll/cancel/status/result);
        the raw child Agent never crosses into the parent's workspace (the
        REPL boundary contract — see :class:`WorkspaceAgent`).
        """
        for key in kwargs:
            if key not in _SPAWN_PASS_THROUGH:
                match = difflib.get_close_matches(key, _SPAWN_PASS_THROUGH, n=1)
                hint = (
                    f" (did you mean {match[0]!r}?)"
                    if match
                    else f" (accepted keyword pass-throughs: {', '.join(repr(k) for k in sorted(_SPAWN_PASS_THROUGH))})"
                )
                raise TypeError(f"spawn() got unexpected keyword {key!r}{hint}")
        if self._runtime is None:
            raise RuntimeError("agent is not attached to a runtime")
        # Runtime.spawn already registered the child on this agent's
        # children list (parent_id was passed) and returns the handle.
        return self._runtime.spawn(
            requirement=requirement,
            acceptance=acceptance,
            parent_id=self.id,
            on_done=on_done,
            agent_callback=True,
            **kwargs,
        )

    # -- directed messaging (framework primitive, 0015) ---------------------

    def send(self, recipient_id: str, body: str):
        """Send a direct message to *recipient_id* (INFO-015, decision 0015).

        Delegates to :meth:`Runtime.send` — the framework's communication
        primitive. The message is delivered on the recipient's own event
        stream (digest, recent context, ``events`` tool) with no channel
        tooling installed; rooms, escalation, and operator questions are
        composed policies over this primitive (``dhc.tooling``), so the
        agent keeps full control of how it communicates.
        """
        if self._runtime is None:
            raise RuntimeError("agent is not attached to a runtime")
        return self._runtime.send(self.id, recipient_id, body)

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

    def record_result(self, reason: str = "cancelled") -> Result:
        """Record a not-ok last result with *reason* (does NOT cancel).

        Named ``record_result`` (not ``cancel``) because it only records a
        not-ok result — the pump settles the agent as *failed* with that
        reason. The REAL cancel is :meth:`AgentHandle.cancel` (which
        delegates to ``Runtime.cancel`` and settles as *cancelled*). A
        method named ``cancel`` that does not cancel is a trap (F10).
        """
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
    REPL surface and cannot mutate the child. There is deliberately no
    ``get()`` unwrap — the raw :class:`Agent` is reachable only
    framework-side via ``Runtime.get``.
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


# --------------------------------------------------------------------------- #
# The REPL-facing surface (the hard boundary)
# --------------------------------------------------------------------------- #

#: The declared public surface of :class:`WorkspaceAgent` — the only agent
#: names agent-authored blocks may rely on. Anything else reachable on the
#: object is out of contract and may change or vanish without notice.
AGENT_SURFACE: frozenset[str] = frozenset(
    {
        # identity / lifecycle (read-only)
        "id",
        "requirement",
        "acceptance",
        "parent_id",
        "children",
        "done",
        "created_ts",
        "settled_ts",
        # token/cost accounting (read-only, IMP-004)
        "prompt_tokens",
        "completion_tokens",
        "cached_tokens",
        "tokens",
        "cost_usd",
        # actions
        "spawn",
        "send",
        "complete",
        "fail",
        "record_result",
        # queries
        "status",
        "result",
        "tool",
        # supervision
        "await_",
        "poll",
        "children_of",
    }
)


@runtime_checkable
class AgentSurface(Protocol):
    """The declared contract of the ``agent`` object inside a workspace.

    Agent-authored blocks see a :class:`WorkspaceAgent` facade; this
    protocol is the contract that facade promises (and the boundary tests
    pin). The raw :class:`Agent` remains framework-side: the pump, the
    settle path, and the driver seam (INFO-051) keep using it.
    """

    id: str
    requirement: str
    acceptance: tuple
    parent_id: Optional[str]
    children: tuple
    done: bool

    def spawn(
        self,
        requirement: str,
        acceptance: tuple = (),
        on_done: Optional[Callable[[Any], None]] = None,
        **kwargs: Any,
    ) -> "AgentHandle": ...

    def send(self, recipient_id: str, body: str) -> Any: ...

    def complete(self, headline: str, artifacts: tuple = ()) -> Result: ...

    def fail(self, reason: str) -> Result: ...

    def record_result(self, reason: str = "cancelled") -> Result: ...

    def status(self) -> Result: ...

    def result(self) -> Result: ...

    def tool(
        self, callable: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> "ToolResult": ...

    def await_(self, child: "AgentHandle") -> Any: ...

    def poll(self, child: "AgentHandle") -> AgentStatus: ...

    def children_of(self, child: "AgentHandle") -> list: ...


class WorkspaceAgent:
    """The ``agent`` object action blocks see — a narrow, delegating facade.

    The runtime injects this into every REPL namespace (and derives every
    namespace action callable from it) instead of the raw :class:`Agent`.
    It forwards the declared :data:`AGENT_SURFACE` — identity, accounting
    reads, actions, supervision — and nothing else:

    * no ``_runtime`` — the whole runtime is not one attribute away;
    * no ``_status`` / ``_result`` / ``_last_result`` — settlement state is
      not writable from a block; the :class:`~dhc.models.CompletionLog`
      stays the single source of truth for at-most-once (INFO-046);
    * ``children`` is a tuple copy — a block cannot forge or drop sibling
      ids;
    * ``spawn`` returns an :class:`AgentHandle`, never a raw child.

    This is a declared-surface boundary, not a sandbox: blocks can still
    import modules and introspect closures, and the driver seam (INFO-051 —
    runtime machinery) legitimately receives the raw Agent. The contract
    is what agent-authored code may rely on — and what the boundary tests
    pin — so the surface cannot silently grow.
    """

    __slots__ = ("_agent",)

    def __init__(self, agent: "Agent") -> None:
        self._agent = agent

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"WorkspaceAgent(id={self.id!r})"

    def __dir__(self) -> list[str]:
        """Advertise only the declared surface."""
        return sorted(AGENT_SURFACE)

    # -- identity / lifecycle (read-only views) -------------------------------

    @property
    def id(self) -> str:
        return self._agent.id

    @property
    def requirement(self) -> str:
        return self._agent.requirement

    @property
    def acceptance(self) -> tuple:
        return self._agent.acceptance

    @property
    def parent_id(self) -> Optional[str]:
        return self._agent.parent_id

    @property
    def children(self) -> tuple:
        """A copy of the child ids — mutation affects nothing."""
        return tuple(self._agent.children)

    @property
    def done(self) -> bool:
        return self._agent.done

    @property
    def created_ts(self) -> float:
        return self._agent.created_ts

    @property
    def settled_ts(self) -> Optional[float]:
        return self._agent.settled_ts

    # -- token/cost accounting (read-only, IMP-004) ----------------------------

    @property
    def prompt_tokens(self) -> int:
        return self._agent.prompt_tokens

    @property
    def completion_tokens(self) -> int:
        return self._agent.completion_tokens

    @property
    def cached_tokens(self) -> int:
        return self._agent.cached_tokens

    @property
    def tokens(self) -> int:
        return self._agent.tokens

    @property
    def cost_usd(self) -> float:
        return self._agent.cost_usd

    # -- actions / queries / supervision: pure delegation -----------------------

    def spawn(
        self,
        requirement: str,
        acceptance: tuple = (),
        on_done: Optional[Callable[[Any], None]] = None,
        **kwargs: Any,
    ) -> "AgentHandle":
        """Spawn a child and return its handle (never the raw child)."""
        return self._agent.spawn(
            requirement, acceptance=acceptance, on_done=on_done, **kwargs
        )

    def send(self, recipient_id: str, body: str) -> Any:
        return self._agent.send(recipient_id, body)

    def complete(self, headline: str, artifacts: tuple = ()) -> Result:
        return self._agent.complete(headline, artifacts)

    def fail(self, reason: str) -> Result:
        return self._agent.fail(reason)

    def record_result(self, reason: str = "cancelled") -> Result:
        return self._agent.record_result(reason)

    def status(self) -> Result:
        return self._agent.status()

    def result(self) -> Result:
        return self._agent.result()

    def tool(
        self, callable: Callable[..., Any], *args: Any, **kwargs: Any
    ) -> "ToolResult":
        return self._agent.tool(callable, *args, **kwargs)

    def await_(self, child: Any) -> Any:
        return self._agent.await_(child)

    def poll(self, child: Any) -> AgentStatus:
        return self._agent.poll(child)

    def children_of(self, child: Any) -> list:
        return self._agent.children_of(child)