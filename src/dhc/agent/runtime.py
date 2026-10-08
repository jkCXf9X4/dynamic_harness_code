"""The runtime orchestrator.

Owns the agent registry, thread-per-agent placement (INFO-038), completion
dispatch (at-most-once, INFO-046), parent liveness (INFO-014), and
cancellation (INFO-034/040). The worker loop (driver -> turn -> settle) and
the pumped ``__runner`` path live in :mod:`dhc.agent.loop`; the ceiling-caps
watchdog predicate lives in :mod:`dhc.agent.caps`; the fabrication
ensure/re-seed helper lives in :mod:`dhc.agent.integrity`. This module keeps
the runtime state (the 17 dicts/flags + the one RLock), settlement, the
namespace build, the public supervision API, and thin method wrappers over
every moved name — the re-export seam — so existing imports (including
tests importing privates) keep working.

All collaborators (engine, event bus, artifact store, settings) are injected
via the constructor — duck-typed, never imported from sibling modules at
module level. When a collaborator is omitted, a lightweight in-memory default
is created so the runtime is usable standalone; the real modules are wired by
the integration agent later.
"""

from __future__ import annotations

import threading
import time
import traceback
from typing import Any, Callable, Optional

from .agent import Agent, AgentHandle, bash
from ..errors import ChannelError, TurnError, TurnTimeoutError  # noqa: F401 - re-export
from ..llm.fabrication import DEFAULT_RUNNER_SOURCE, fabrication_kit
from ..data.models import (
    TERMINAL_STATES,
    AgentStatus,
    Artifact,
    Completion,
    CompletionLog,
    Event,
    EventKind,
    Result,
    is_terminal,
)

# The loop concern (moved verbatim; thin wrappers below re-export it).
from . import loop as _loop
from .loop import (  # noqa: F401 - re-export (yield vocab, D3 + moved loop callables)
    Await,
    Poll,
    Sleep,
    install_runner,
    legacy_loop,
    pump_agent,
    pump_loop,
    service_await,
    service_sleep,
    step_timeout,
    supports_pump,
)
from .caps import (  # noqa: F401 - re-export (caps defaults moved with the watchdog)
    _DEFAULT_MAX_CHILDREN,
    _DEFAULT_MAX_ITERATIONS,
    _DEFAULT_MAX_MESSAGES_PER_STEP,
    _DEFAULT_TIMEOUT_SECONDS,
    _DEFAULT_MAX_WORKSPACE_BYTES,
)
from .loop import _DEFAULT_STEP_TIMEOUT  # noqa: F401 - re-export
from . import caps as _caps
from . import integrity as _integrity


# --------------------------------------------------------------------------- #
# Lightweight in-memory defaults (standalone use; real modules injected later)
# --------------------------------------------------------------------------- #


class _MemoryEngine:
    """A simple engine that executes code with exec() in a per-agent dict."""

    def __init__(self) -> None:
        self._namespaces: dict[str, dict] = {}
        self._lock = threading.Lock()

    def execute(
        self,
        agent_id: str,
        code: str,
        namespace: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> None:
        del timeout  # in-memory engine executes synchronously
        with self._lock:
            ns = self._namespaces.setdefault(agent_id, {})
            if namespace is not None:
                ns.update(namespace)
            exec(compile(code, f"<agent:{agent_id}>", "exec"), ns)


class _MemoryBus:
    """A simple in-memory event bus: publish appends to per-topic queues."""

    def __init__(self) -> None:
        self._queues: dict[str, list] = {}
        self._lock = threading.Lock()

    def publish(self, topic: str, event: Any) -> None:
        with self._lock:
            self._queues.setdefault(topic, []).append(event)

    def drain(self, topic: str) -> list:
        with self._lock:
            items = list(self._queues.get(topic, []))
            self._queues[topic] = []
            return items

    def peek(self, topic: str) -> list:
        """Return the topic's events without consuming them (fan-out seam).

        The drain-race fix: consumers of the ``events:<id>`` topics read
        through this non-destructive peek and keep their own cursor, so no
        consumer steals another's events. ``drain`` stays destructive (the
        ``completions:<id>`` contract, INFO-046 at-most-once).
        """
        with self._lock:
            return list(self._queues.get(topic, []))


class _MemoryStore:
    """A simple in-memory artifact store (content-addressed)."""

    def __init__(self) -> None:
        self._artifacts: dict[str, Artifact] = {}
        self._lock = threading.Lock()

    def publish(self, headline: str, summary: str, report: Any) -> Artifact:
        artifact = Artifact(headline=headline, summary=summary, report=report)
        with self._lock:
            self._artifacts[artifact.id] = artifact
        return artifact

    def get(self, artifact_id: str) -> Optional[Artifact]:
        with self._lock:
            return self._artifacts.get(artifact_id)


# --------------------------------------------------------------------------- #
# Runtime
# --------------------------------------------------------------------------- #


class Runtime:
    """The orchestrator: spawn/await/poll/cancel/status/result per agent.

    Public API (per contract §4):

    - ``start()`` / ``stop()``
    - ``spawn(requirement, acceptance=(), driver=None, on_done=None) -> AgentHandle``
    - ``await_(agent_id) -> Completion`` (ensure-terminal)
    - ``poll(agent_id) -> AgentStatus`` (non-blocking)
    - ``cancel(agent_id, reason="cancelled") -> Result``
    - ``status(agent_id) -> AgentStatus``
    - ``result(agent_id) -> Result``
    - ``get(agent_id) -> Agent``
    - ``children_of(agent_id) -> list[str]``
    - ``is_settled(agent_id) -> bool``

    ``await`` is a Python keyword, so the blocking join is named ``await_``
    (documented deviation; the operation is unchanged).
    """

    def __init__(
        self,
        engine: Any = None,
        event_bus: Any = None,
        artifact_store: Any = None,
        settings: Any = None,
    ) -> None:
        self.engine = engine if engine is not None else _MemoryEngine()
        self.event_bus = event_bus if event_bus is not None else _MemoryBus()
        self.artifact_store = (
            artifact_store if artifact_store is not None else _MemoryStore()
        )
        self.settings = settings

        self._agents: dict[str, Agent] = {}
        self._handles: dict[str, AgentHandle] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._stop_flags: dict[str, threading.Event] = {}
        self._completions: dict[str, Completion] = {}
        self._completion_log = CompletionLog()
        # Agent-level completion callbacks (registered via Agent.spawn) run in
        # the parent's worker loop between actions, in completion order.
        self._parent_callbacks: dict[str, list[Callable[[Completion], None]]] = {}
        # Host-level completion callbacks (registered via Runtime.spawn) run in
        # the settling thread.
        self._host_callbacks: dict[str, list[Callable[[Completion], None]]] = {}
        # Delivered completions per parent (the parent's completion stream).
        self._delivered: dict[str, list[Completion]] = {}
        # Per-agent read cursors over the non-destructive ``events:<id>``
        # peek (the drain-race fix): each consumer of the fan-out seam
        # advances its own cursor, so events are never stolen between
        # consumers. ``_event_cursors`` backs ``Runtime.events`` (the
        # public API keeps its consume-once semantics); ``_caps_cursors``
        # backs the message-rate cap's per-step delta.
        self._event_cursors: dict[str, int] = {}
        self._caps_cursors: dict[str, int] = {}
        # Per-agent read cursor for the agent-facing ``events`` tool (G-04):
        # the agent's own consume-once view over the same non-destructive
        # ``events:<id>`` peek. Kept separate from ``_event_cursors`` (the
        # default runner's observe) so the agent can consume on its own
        # schedule without stealing from the default loop's digest.
        self._tool_event_cursors: dict[str, int] = {}
        self._extra_namespace: dict[str, dict] = {}
        self._lock = threading.RLock()
        self._id_counter = 0
        self._started = False
        self._stopping = False

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Boot the runtime (idempotent)."""
        with self._lock:
            self._started = True

    def stop(self) -> None:
        """Shut down: cancel live agents and join all worker threads."""
        with self._lock:
            self._stopping = True
            agent_ids = list(self._agents)
        for agent_id in agent_ids:
            self.cancel(agent_id, reason="runtime stopped")
        threads = list(self._threads.values())
        for thread in threads:
            thread.join(timeout=2.0)

    # -- spawning ------------------------------------------------------------

    def _new_agent_id(self) -> str:
        with self._lock:
            self._id_counter += 1
            return f"a{self._id_counter}"

    def spawn(
        self,
        requirement: str,
        acceptance: tuple = (),
        driver: Optional[Callable[[Agent], Optional[str]]] = None,
        on_done: Optional[Callable[[Completion], None]] = None,
        parent_id: Optional[str] = None,
        namespace: Optional[dict] = None,
        _agent_callback: bool = False,
    ) -> AgentHandle:
        """Spawn a new agent (non-blocking) and start its worker thread.

        *driver* is the pluggable brain: called with the Agent, it returns the
        next code block to execute, or None to settle. Tests use scripted
        drivers; the LLM loop is wired later.

        *on_done* registers a completion callback. When ``_agent_callback`` is
        True (Agent.spawn), the callback runs in the parent's worker loop
        between actions, in completion order. Otherwise it is a host-level
        callback that runs when the agent settles.

        *namespace* optionally injects extra names (callables, values) into
        the agent's turn namespace — the seam tests use to hand scripted
        drivers to spawned children.
        """
        with self._lock:
            if not self._started:
                self._started = True
            agent_id = self._new_agent_id()
            agent = Agent(
                id=agent_id,
                requirement=requirement,
                acceptance=tuple(acceptance),
                parent_id=parent_id,
                runtime=self,
                artifact_store=self.artifact_store,
            )
            self._agents[agent_id] = agent
            self._handles[agent_id] = AgentHandle(agent_id, self)
            self._stop_flags[agent_id] = threading.Event()
            if on_done is not None:
                target = self._parent_callbacks if _agent_callback else self._host_callbacks
                target.setdefault(agent_id, []).append(on_done)
            if namespace:
                self._extra_namespace[agent_id] = dict(namespace)
            if parent_id is not None and parent_id in self._agents:
                self._agents[parent_id].children.append(agent_id)
                self._emit(
                    parent_id,
                    EventKind.child_spawned,
                    payload={"child_id": agent_id},
                )
            thread = threading.Thread(
                target=self._pump_agent,
                args=(agent_id, driver),
                name=f"dhc-agent-{agent_id}",
                daemon=True,
            )
            self._threads[agent_id] = thread
            thread.start()
        return self._handles[agent_id]

    # -- worker loop (moved to dhc.agent.loop; thin wrappers) -----------------

    def _supports_pump(self) -> bool:
        """True when the engine can drive a resumable ``__runner`` generator."""
        return _loop.supports_pump(self)

    def _step_timeout(self) -> float:
        """The per-step timeout the pump passes to ``engine.advance``."""
        return _loop.step_timeout(self)

    def _pump_agent(self, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]) -> None:
        """Drive *agent_id* to settlement (IMP-001 Step 3). Moved to
        :func:`dhc.agent.loop.pump_agent`; thin wrapper (re-export seam)."""
        return _loop.pump_agent(self, agent_id, driver)

    def _legacy_loop(self, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]) -> None:
        """The legacy turn loop (non-pump engines only). Moved to
        :func:`dhc.agent.loop.legacy_loop`; thin wrapper (re-export seam)."""
        return _loop.legacy_loop(self, agent_id, driver)

    def _pump_loop(self, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]) -> None:
        """The ONE loop for the real runtime: drive the agent's ``__runner``
        one yield-window per step under the four hard gates. Moved to
        :func:`dhc.agent.loop.pump_loop`; thin wrapper (re-export seam)."""
        return _loop.pump_loop(self, agent_id, driver)

    def _install_runner(
        self,
        engine: Any,
        agent_id: str,
        kit: dict,
        source: Optional[str] = None,
    ) -> str:
        """Compile and install the agent's ``__runner`` generator. Moved to
        :func:`dhc.agent.loop.install_runner`; thin wrapper (re-export seam)."""
        return _loop.install_runner(engine, agent_id, kit, source)

    def _service_await(self, agent_id: str, engine: Any, handle: Any) -> bool:
        """Park the runner until *handle*'s agent settles. Moved to
        :func:`dhc.agent.loop.service_await`; thin wrapper (re-export seam)."""
        return _loop.service_await(self, agent_id, engine, handle)

    def _service_sleep(self, agent_id: str, engine: Any, seconds: float) -> bool:
        """Park the runner for *seconds* (stop-flag aware). Moved to
        :func:`dhc.agent.loop.service_sleep`; thin wrapper (re-export seam)."""
        return _loop.service_sleep(self, agent_id, engine, seconds)

    # -- ceiling caps (predicate moved to dhc.agent.caps) --------------------

    def _cap(self, name: str, default: Any) -> Any:
        """Read a cap from settings None-safely (safety config first)."""
        return _caps.read_cap(self.settings, name, default)

    def _cap_limit(self, cap: str) -> Any:
        """The configured limit for a cap name (for the crash event payload)."""
        return _caps.cap_limit(cap, self.settings)

    def _caps_watchdog(
        self,
        agent_id: str,
        engine: Any,
        step_count: int,
        started_ts: float,
    ) -> Optional[str]:
        """Return the name of the first ceiling cap exceeded, else None.

        Moved to :func:`dhc.agent.caps.caps_exceeded`; this wrapper supplies
        the runtime-state reads as lazy thunks (the lock-guarded child count
        and the event-bus drain — the drain runs only when the message-rate
        cap is enabled, exactly as before).
        """

        def _child_count() -> int:
            with self._lock:
                return len(self._agents[agent_id].children)

        def _pending_messages() -> int:
            # Drain-race fix: peek (non-destructive) + a per-step delta
            # cursor. The historical drain counted whatever was pending at
            # the instant the cap ran — a per-step delta, not a cumulative
            # total — so the cursor keeps exactly that semantics while the
            # peek stops the watchdog from consuming the other consumers'
            # events.
            peek = getattr(self.event_bus, "peek", None)
            if peek is None:
                # A bus without the fan-out seam: the destructive drain is
                # itself the per-step delta (it clears the topic).
                try:
                    return len(self.event_bus.drain(f"events:{agent_id}"))
                except Exception:  # noqa: BLE001 - counting is best-effort
                    return 0
            try:
                events = peek(f"events:{agent_id}")
            except Exception:  # noqa: BLE001 - counting is best-effort
                return 0
            with self._lock:
                seen = self._caps_cursors.get(agent_id, 0)
                if len(events) < seen:
                    # The stream shrank underneath us (a foreign destructive
                    # drain): count from the start rather than skip events.
                    seen = 0
                fresh = max(len(events) - seen, 0)
                self._caps_cursors[agent_id] = len(events)
            return fresh

        return _caps.caps_exceeded(
            agent_id,
            engine,
            step_count,
            started_ts,
            settings=self.settings,
            child_count=_child_count,
            pending_messages=_pending_messages,
        )

    # -- namespace -----------------------------------------------------------

    def _build_namespace(self, agent: Agent) -> dict:
        """Build the in-code namespace for one turn from the Agent.

        CORE-ONLY names (the architectural goal: core = runtime + eventbus).
        The artifact store and communication channels are REPL tools composed
        in by :func:`dhc.tools.register_default_tools` (via wiring.py), not
        part of the core namespace.
        """
        ns = {
            "agent": agent,
            "spawn": agent.spawn,
            "complete": agent.complete,
            "fail": agent.fail,
            "cancel": agent.cancel,
            "status": agent.status,
            "result": agent.result,
            "tool": agent.tool,
            "bash": bash,
            "await_": agent.await_,
            "poll": agent.poll,
            "children_of": agent.children_of,
            "Await": Await,
            "Poll": Poll,
            "Sleep": Sleep,
        }
        extra = self._extra_namespace.get(agent.id)
        if extra:
            ns.update(extra)
        return ns

    def _max_turn_seconds(self) -> Optional[float]:
        if self.settings is None:
            return None
        return getattr(self.settings, "max_turn_seconds", None)

    # -- parent liveness -----------------------------------------------------

    def _wait_children_settled(self, agent_id: str) -> bool:
        """Block until every child of *agent_id* has settled.

        Returns False if the agent was cancelled while waiting.
        """
        while True:
            if self._stop_flags[agent_id].is_set():
                return False
            with self._lock:
                agent = self._agents[agent_id]
                unsettled = [
                    cid
                    for cid in agent.children
                    if not is_terminal(self._agents[cid]._status)
                ]
            if not unsettled:
                return True
            time.sleep(0.01)

    # -- completion dispatch -------------------------------------------------

    def _drain_completions(self, agent_id: str) -> None:
        """Run *agent_id*'s pending completion callbacks, in completion order.

        Called by the parent's own worker loop between actions — never
        concurrently with parent action code (INFO-039/047).
        """
        completions = self.event_bus.drain(f"completions:{agent_id}")
        if not completions:
            return
        with self._lock:
            self._delivered.setdefault(agent_id, []).extend(completions)
            callbacks = [
                (completion, list(self._parent_callbacks.get(completion.agent_id, [])))
                for completion in completions
            ]
        for completion, cbs in callbacks:
            for callback in cbs:
                try:
                    callback(completion)
                except Exception:  # noqa: BLE001 - a bad callback never breaks the runtime
                    traceback.print_exc()

    # -- settlement ----------------------------------------------------------

    def _settle(
        self,
        agent_id: str,
        status: AgentStatus,
        summary: str = "",
        reason: str = "",
    ) -> None:
        """Settle *agent_id* at most once; dispatch its completion to the parent."""
        with self._lock:
            agent = self._agents[agent_id]
            if is_terminal(agent._status):
                return  # already settled; at-most-once
            completion = Completion(
                agent_id=agent_id,
                status=status,
                summary=summary,
                artifact_ids=list(agent._last_result.artifacts) if agent._last_result else [],
                reason=reason,
            )
            try:
                self._completion_log.settle(completion)
            except ChannelError:
                return  # at-most-once: first settlement wins
            self._completions[agent_id] = completion
            parent_id = agent.parent_id
            host_callbacks = list(self._host_callbacks.get(agent_id, []))
        # Publish to the parent's stream BEFORE marking terminal, so a parent
        # that observes the child terminal is guaranteed to see the completion.
        if parent_id is not None and parent_id in self._agents:
            try:
                self.event_bus.publish(f"completions:{parent_id}", completion)
            except Exception:  # noqa: BLE001 - a bad bus never breaks settlement
                traceback.print_exc()
        with self._lock:
            agent._status = status
            agent.settled_ts = time.time()
            if agent._result is None:
                if status == AgentStatus.completed:
                    agent._result = Result(done=True, ok=True, value=summary)
                else:
                    agent._result = Result(done=True, ok=False, reason=reason or status.value)
            self._emit(
                agent_id,
                EventKind.child_settled,
                payload={"status": status.value, "summary": summary, "reason": reason},
            )
        for callback in host_callbacks:
            try:
                callback(completion)
            except Exception:  # noqa: BLE001 - a bad callback never breaks the runtime
                traceback.print_exc()

    def _emit(self, agent_id: str, kind: EventKind, payload: Optional[dict] = None) -> None:
        event = Event(kind=kind, agent_id=agent_id, payload=payload or {})
        self.event_bus.publish(f"events:{agent_id}", event)

    # -- public supervision API ----------------------------------------------

    def await_(self, agent_id: str) -> Completion:
        """Ensure-terminal: block until *agent_id* settles, return its Completion."""
        while True:
            with self._lock:
                if agent_id in self._completions:
                    return self._completions[agent_id]
                if agent_id not in self._agents:
                    raise KeyError(f"unknown agent {agent_id!r}")
            time.sleep(0.005)

    def poll(self, agent_id: str) -> AgentStatus:
        """Non-blocking: return the agent's current lifecycle state."""
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"unknown agent {agent_id!r}")
            return self._agents[agent_id]._status

    def cancel(self, agent_id: str, reason: str = "cancelled") -> Result:
        """Cancel the agent's worker; it settles as cancelled (INFO-034/040)."""
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"unknown agent {agent_id!r}")
            agent = self._agents[agent_id]
            if is_terminal(agent._status):
                return agent.result() or Result(done=True, ok=False, reason=reason)
            self._stop_flags[agent_id].set()
            agent._last_result = Result(done=True, ok=False, reason=reason)
            thread = self._threads.get(agent_id)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        # If the worker was blocked in a long turn, settle it here so the
        # cancellation is observable even before the worker notices.
        with self._lock:
            if not is_terminal(agent._status):
                self._settle(agent_id, AgentStatus.cancelled, reason=reason)
        return self.result(agent_id)

    def status(self, agent_id: str) -> AgentStatus:
        """Return the agent's current lifecycle state."""
        return self.poll(agent_id)

    def result(self, agent_id: str) -> Result:
        """Return the agent's settled result."""
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"unknown agent {agent_id!r}")
            return self._agents[agent_id].result()

    def get(self, agent_id: str) -> Agent:
        """Return the underlying Agent object."""
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"unknown agent {agent_id!r}")
            return self._agents[agent_id]

    def children_of(self, agent_id: str) -> list:
        """Return the ids of *agent_id*'s children."""
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"unknown agent {agent_id!r}")
            return list(self._agents[agent_id].children)

    def is_settled(self, agent_id: str) -> bool:
        """True once *agent_id* has reached a terminal state."""
        with self._lock:
            if agent_id not in self._agents:
                raise KeyError(f"unknown agent {agent_id!r}")
            return is_terminal(self._agents[agent_id]._status)

    # -- completion stream (runtime-owned dispatch) --------------------------

    def completions(self, agent_id: str) -> list:
        """Return the completions delivered on *agent_id*'s stream, in order."""
        with self._lock:
            return list(self._delivered.get(agent_id, []))

    def events(self, agent_id: str) -> list:
        """Return the events emitted by *agent_id*, in order.

        Drain-race fix: reads the non-destructive peek and advances this
        runtime's per-agent cursor, so the call keeps its historical
        consume-once semantics (a second call returns only events published
        since the first) without stealing events from the other consumers
        of the fan-out seam (the caps watchdog, the driver's recent
        context, the StateWriter poll thread).
        """
        topic = f"events:{agent_id}"
        peek = getattr(self.event_bus, "peek", None)
        if peek is None:
            # A bus without the fan-out seam: fall back to the destructive
            # drain (the pre-fix contract).
            return list(self.event_bus.drain(topic))
        events = peek(topic)
        with self._lock:
            cursor = self._event_cursors.get(agent_id, 0)
            if len(events) < cursor:
                # The stream shrank underneath us (a foreign destructive
                # drain): re-read from the start rather than skip events.
                cursor = 0
            fresh = events[cursor:]
            self._event_cursors[agent_id] = len(events)
        return list(fresh)

    def tool_events(self, agent_id: str) -> list:
        """The agent-facing settled-event stream (G-04), consume-once.

        The same non-destructive ``events:<id>`` peek as :meth:`events`, but
        with the *tool's own* per-agent cursor (``_tool_event_cursors``).
        This is the surface the ``events`` workspace tool wraps: the agent
        reads its own settled events on its own schedule (its choice, per
        INFO-053) without rewriting the runner, and without stealing events
        from the default runner's ``observe`` (which keeps ``_event_cursors``)
        or from the caps watchdog (``_caps_cursors``). The discipline
        guarantees (FIFO, at-most-once, persist-before-execute) remain
        runtime-owned: this only advances a read cursor over the already
        persisted, ordered stream.
        """
        topic = f"events:{agent_id}"
        peek = getattr(self.event_bus, "peek", None)
        if peek is None:
            # A bus without the fan-out seam: fall back to the destructive
            # drain (the pre-fix contract), same as :meth:`events`.
            return list(self.event_bus.drain(topic))
        events = peek(topic)
        with self._lock:
            cursor = self._tool_event_cursors.get(agent_id, 0)
            if len(events) < cursor:
                # The stream shrank underneath us (a foreign destructive
                # drain): re-read from the start rather than skip events.
                cursor = 0
            fresh = events[cursor:]
            self._tool_event_cursors[agent_id] = len(events)
        return list(fresh)

    def completion_log(self) -> CompletionLog:
        """Return the at-most-once settlement registry."""
        return self._completion_log
