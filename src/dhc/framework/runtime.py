"""The runtime orchestrator.

Owns the agent registry, thread-per-agent placement (INFO-038), completion
dispatch (at-most-once, INFO-046), parent liveness (INFO-014), and
cancellation (INFO-034/040). The worker loop (driver -> turn -> settle) and
the pumped ``__runner`` path live in :mod:`dhc.framework.pump`; the ceiling-caps
watchdog predicate lives in :mod:`dhc.framework.caps`; the fabrication
ensure/re-seed helper lives in :mod:`dhc.framework.integrity`. This module keeps
the runtime state (the 17 dicts/flags + the one RLock), settlement, the
namespace build, the public supervision API, and thin method wrappers over
every moved name — the re-export seam — so existing imports (including
tests importing privates) keep working.

All collaborators (engine, event bus, settings) are injected
via the constructor — duck-typed, never imported from sibling modules at
module level. When a collaborator is omitted, a lightweight in-memory default
is created so the runtime is usable standalone; the real modules are wired by
the integration agent later. The runtime is store-unaware (decision 0014):
artifact persistence is operator tooling (``dhc.tooling``) composed in by the
composition root, not a core collaborator. Directed agent-to-agent messaging
IS core (decision 0015): :meth:`Runtime.send` is the framework's
communication primitive — a receiver-addressed ``message_sent`` event on the
recipient's own stream. Channel policies (rooms, escalation, operator
questions) are tooling composed over that primitive, never runtime
collaborators. The default AGENT is composition too (decision 0017): the
pump drives whatever loop a workspace holds, and the birth kit — the
default ``__runner__`` + ``decide`` + context + helpers — is handed in
via ``kit_factory`` (the composition root passes
``tooling.fabrication.fabrication_kit``); the framework carries the
runner contract, not the loop's content.
"""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from typing import Any, Callable, Optional

from .agent import Agent, AgentHandle, WorkspaceAgent, bash
from .surface import SurfaceEntry, default_registry
from ..errors import (  # noqa: F401 - re-export
    ChannelError,
    TurnError,
    TurnTimeoutError,
    UnknownAgentError,
)
from ..data.models import (
    TERMINAL_STATES,
    AgentStatus,
    Completion,
    CompletionLog,
    Event,
    EventKind,
    Result,
    is_terminal,
)

# The loop concern (moved verbatim; thin wrappers below re-export it).
from . import pump as _loop
from .pump import (  # noqa: F401 - re-export (yield vocab, D3 + moved loop callables)
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
    _DEFAULT_MAX_WORKSPACE_BYTES,
)
from .pump import _DEFAULT_STEP_TIMEOUT  # noqa: F401 - re-export
from . import caps as _caps
from . import integrity as _integrity


def _crossing_snapshot(events: list) -> list:
    """Copy events as they cross the framework→REPL boundary.

    ``Event`` is a frozen model, but its ``payload`` dict is shared by
    every holder. Handing REPL code a deep copy keeps post-emission
    mutation a private edit: the stream's pending events, the messenger's
    stored copies, and every other in-memory consumer keep the emitted
    values. Duck-typed events (non-pydantic) pass through untouched.
    """
    return [
        event.model_copy(deep=True) if hasattr(event, "model_copy") else event
        for event in events
    ]


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
    - ``send(sender_id, recipient_id, body) -> Event`` (direct message, 0015)

    ``await`` is a Python keyword, so the blocking join is named ``await_``
    (documented deviation; the operation is unchanged).
    """

    def __init__(
        self,
        engine: Any = None,
        event_bus: Any = None,
        settings: Any = None,
        kit_factory: Optional[Callable[..., dict]] = None,
    ) -> None:
        self.engine = engine if engine is not None else _MemoryEngine()
        self.event_bus = event_bus if event_bus is not None else _MemoryBus()
        self.settings = settings
        # Decision 0017: the birth-kit seam. The pump drives whatever
        # loop a workspace holds; the DEFAULT agent (the fabrication kit)
        # is composition — the composition root hands its factory in
        # here. None means the pumped path cannot birth an agent (a bare
        # Runtime uses the legacy loop anyway; the pump settles failed
        # with a clear reason if reached without one).
        self.kit_factory = kit_factory

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
        # W1.3: the ordered namespace-builder chain. The core names come
        # from _core_namespace (always first); every registration function
        # (framework tools, channel tools, artifact tools, the wiring root)
        # appends its builder here instead of reassigning _build_namespace.
        self._namespace_builders: list[tuple[str, Callable[[Agent], dict]]] = []
        self._lock = threading.RLock()
        # W1.2: the core surface is registered in the process-wide
        # registry (the single source of truth the prompt and list_tools
        # are generated from). Idempotent: re-registering replaces.
        _register_core_surface()
        self._id_counter = 0
        self._started = False
        self._stopping = False

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> None:
        """Boot the runtime.

        IDEMPOTENT: calling it more than once is a no-op. It only marks the
        runtime started — it does NOT start any agents. ``spawn()``
        auto-starts each agent's worker thread (and marks the runtime
        started as a side effect), so a fresh runtime needs no explicit
        ``start()`` before the first ``spawn()``.
        """
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
        agent_callback: bool = False,
    ) -> AgentHandle:
        """Spawn a new agent (non-blocking) and start its worker thread.

        *driver* is the pluggable brain: called with the Agent, it returns the
        next code block to execute, or None to settle. Tests use scripted
        drivers; the LLM loop is wired later.

        *on_done* registers a completion callback. When *agent_callback* is
        True (the internal ``Agent.spawn`` path), the callback is routed to
        the parent-agent callback registry and runs in the parent's worker
        loop between actions, in completion order. Otherwise (the default)
        it is a host-level callback that runs when the agent settles.

        *namespace* optionally injects extra names (callables, values) into
        the agent's turn namespace — the seam tests use to hand scripted
        drivers to spawned children.

        ``spawn()`` auto-starts the agent's worker thread; :meth:`start`
        only boots the runtime itself (idempotent).
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
            )
            self._agents[agent_id] = agent
            self._handles[agent_id] = AgentHandle(agent_id, self)
            self._stop_flags[agent_id] = threading.Event()
            if on_done is not None:
                target = self._parent_callbacks if agent_callback else self._host_callbacks
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

    # -- worker loop (moved to dhc.framework.pump; thin wrappers) -----------------

    def _supports_pump(self) -> bool:
        """True when the engine can drive a resumable ``__runner`` generator."""
        return _loop.supports_pump(self)

    def _step_timeout(self) -> float:
        """The per-step timeout the pump passes to ``engine.advance``."""
        return _loop.step_timeout(self)

    def _pump_agent(self, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]) -> None:
        """Drive *agent_id* to settlement (IMP-001 Step 3). Moved to
        :func:`dhc.framework.pump.pump_agent`; thin wrapper (re-export seam)."""
        return _loop.pump_agent(self, agent_id, driver)

    def _legacy_loop(self, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]) -> None:
        """The legacy turn loop (non-pump engines only). Moved to
        :func:`dhc.framework.pump.legacy_loop`; thin wrapper (re-export seam)."""
        return _loop.legacy_loop(self, agent_id, driver)

    def _pump_loop(self, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]) -> None:
        """The ONE loop for the real runtime: drive the agent's ``__runner``
        one yield-window per step under the four hard gates. Moved to
        :func:`dhc.framework.pump.pump_loop`; thin wrapper (re-export seam)."""
        return _loop.pump_loop(self, agent_id, driver)

    def _install_runner(
        self,
        engine: Any,
        agent_id: str,
        kit: dict,
        source: Optional[str] = None,
    ) -> str:
        """Compile and install the agent's ``__runner`` generator. Moved to
        :func:`dhc.framework.pump.install_runner`; thin wrapper (re-export seam)."""
        return _loop.install_runner(engine, agent_id, kit, source)

    def _service_await(self, agent_id: str, engine: Any, handle: Any) -> float:
        """Park the runner until *handle*'s agent settles. Moved to
        :func:`dhc.framework.pump.service_await`; thin wrapper (re-export seam).
        Returns the parked seconds (credited against the wall clock, 0008)."""
        return _loop.service_await(self, agent_id, engine, handle)

    def _service_sleep(self, agent_id: str, engine: Any, seconds: float) -> float:
        """Park the runner for *seconds* (stop-flag aware). Moved to
        :func:`dhc.framework.pump.service_sleep`; thin wrapper (re-export seam).
        Returns the parked seconds (credited against the wall clock, 0008)."""
        return _loop.service_sleep(self, agent_id, engine, seconds)

    # -- ceiling caps (predicate moved to dhc.framework.caps) --------------------

    def _cap(self, name: str, default: Any) -> Any:
        """Read a cap from settings None-safely (safety config first)."""
        return _caps.read_cap(self.settings, name, default)

    def _cap_limit(self, cap: str) -> Any:
        """The configured limit for a cap name (for the crash event payload)."""
        return _caps.cap_limit(cap, self.settings)

    def _caps_hit(
        self,
        agent_id: str,
        engine: Any,
        step_count: int,
        started_ts: float,
        parked_seconds: float = 0.0,
    ) -> Optional[dict]:
        """The first exceeded cap as ``{"cap", "limit", "source"}``, else None.

        G-01: the ceiling-caps predicate with the agent's working budgets
        (``context.budgets``) min-clamped onto each ceiling — the effective
        limit is ``min(agent_budget, ceiling)``, evaluated here in runtime
        code (never in agent code). ``limit`` is the effective (binding)
        value; ``source`` names its origin (``"agent_budget"`` /
        ``"ceiling"``). Supplies the runtime-state reads as lazy thunks
        (the lock-guarded child count and the event-bus drain — the drain
        runs only when the message-rate cap is enabled, exactly as
        before).
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

        return _caps.cap_hit(
            agent_id,
            engine,
            step_count,
            started_ts,
            settings=self.settings,
            child_count=_child_count,
            pending_messages=_pending_messages,
            parked_seconds=parked_seconds,
        )

    def _caps_watchdog(
        self,
        agent_id: str,
        engine: Any,
        step_count: int,
        started_ts: float,
        parked_seconds: float = 0.0,
    ) -> Optional[str]:
        """Return the name of the first ceiling cap exceeded, else None.

        The historical contract (a cap-name string), kept for existing
        callers; the pump reads the enriched view via :meth:`_caps_hit`
        (G-01: effective limit + source for the crash-event payload).
        Parked time is credited against the wall clock (G-05, 0008).
        """
        hit = self._caps_hit(
            agent_id, engine, step_count, started_ts, parked_seconds=parked_seconds
        )
        return hit["cap"] if hit is not None else None

    # -- namespace -----------------------------------------------------------

    def register_namespace_builder(
        self, builder: Callable[[Agent], dict], name: Optional[str] = None
    ) -> None:
        """Append *builder* to the ordered namespace-builder chain (W1.3).

        Each builder takes the Agent and returns namespace additions; the
        composed namespace is the union in registration order (later
        builders may overwrite earlier names). This replaces the historical
        private-method reassignment (``runtime._build_namespace = build``):
        the chain is public, ordered, and inspectable via
        :attr:`namespace_builders`. The core builder (this class's own
        ``_core_namespace``) always runs first.
        """
        with self._lock:
            self._namespace_builders.append((name or getattr(builder, "__name__", "builder"), builder))

    @property
    def namespace_builders(self) -> list[tuple[str, Callable[[Agent], dict]]]:
        """The registered (name, builder) chain, in registration order."""
        return list(self._namespace_builders)

    def _core_namespace(self, agent: Agent) -> dict:
        """The core names every runtime injects (the first builder).

        CORE-ONLY names (the architectural goal: core = runtime + eventbus +
        the directed-message primitive, 0015). The artifact store and the
        communication channels are REPL tools composed in by the registration
        functions (``dhc.tooling.framework_tools``, ``dhc.tooling`` — via wiring.py), not
        part of the core namespace. ``send`` is the one communication name
        here: direct messaging is the framework primitive every agent gets,
        even in a bare runtime with no tooling installed.

        The boundary contract: blocks see the :class:`WorkspaceAgent`
        facade as ``agent`` — never the raw Agent — and every action
        callable is facade-bound, so the raw runtime is not reachable
        through the declared surface (``__self__`` included). Pinned by
        ``tests/framework/test_repl_boundary.py``.
        """
        surface = WorkspaceAgent(agent)
        ns = {
            "agent": surface,
            "spawn": surface.spawn,
            "send": surface.send,
            "complete": surface.complete,
            "fail": surface.fail,
            "record_result": surface.record_result,
            "status": surface.status,
            "result": surface.result,
            "tool": surface.tool,
            "bash": bash,
            "await_": surface.await_,
            "poll": surface.poll,
            "children_of": surface.children_of,
            "Await": Await,
            "Poll": Poll,
            "Sleep": Sleep,
        }
        extra = self._extra_namespace.get(agent.id)
        if extra:
            ns.update(extra)
        return ns

    def _build_namespace(self, agent: Agent) -> dict:
        """Build the in-code namespace for one turn: core + registered builders.

        Composes the core namespace with every builder registered via
        :meth:`register_namespace_builder`, in registration order. The
        historical wrap chain (each registration function reassigning
        ``_build_namespace``) produced exactly this union; this is the same
        composition, made public and inspectable.
        """
        ns = self._core_namespace(agent)
        for _name, builder in self._namespace_builders:
            ns.update(builder(agent))
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
        """Settle *agent_id* at most once; dispatch its completion to the parent.

        The :class:`~dhc.models.CompletionLog` is the single source of
        truth for at-most-once (INFO-046): settlement is gated by the log
        FIRST, so a forged ``agent._status`` (reachable only by reaching
        around the declared surface) can never suppress or duplicate the
        real completion — the log's first entry wins, later attempts are
        rejected.
        """
        with self._lock:
            agent = self._agents[agent_id]
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
                return  # at-most-once: the log's first entry wins
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
                    raise UnknownAgentError(
                        f"unknown agent id {agent_id!r} (runtime knows {len(self._agents)} agents)"
                    )
            time.sleep(0.005)

    def poll(self, agent_id: str) -> AgentStatus:
        """Non-blocking: return the agent's current lifecycle state."""
        with self._lock:
            if agent_id not in self._agents:
                raise UnknownAgentError(
                        f"unknown agent id {agent_id!r} (runtime knows {len(self._agents)} agents)"
                    )
            return self._agents[agent_id]._status

    def cancel(self, agent_id: str, reason: str = "cancelled") -> Result:
        """Cancel the agent's worker; it settles as cancelled (INFO-034/040)."""
        with self._lock:
            if agent_id not in self._agents:
                raise UnknownAgentError(
                        f"unknown agent id {agent_id!r} (runtime knows {len(self._agents)} agents)"
                    )
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
        """Return the agent's current lifecycle state.

        Host-facing alias of :meth:`poll` — identical behavior (including
        raising :class:`~dhc.errors.UnknownAgentError` for an unknown id);
        kept as a distinct name for host/UI callers.
        """
        return self.poll(agent_id)

    def result(self, agent_id: str) -> Result:
        """Return the agent's settled result."""
        with self._lock:
            if agent_id not in self._agents:
                raise UnknownAgentError(
                        f"unknown agent id {agent_id!r} (runtime knows {len(self._agents)} agents)"
                    )
            return self._agents[agent_id].result()

    def get(self, agent_id: str) -> Agent:
        """Return the underlying Agent object."""
        with self._lock:
            if agent_id not in self._agents:
                raise UnknownAgentError(
                        f"unknown agent id {agent_id!r} (runtime knows {len(self._agents)} agents)"
                    )
            return self._agents[agent_id]

    def children_of(self, agent_id: str) -> list:
        """Return the ids of *agent_id*'s children."""
        with self._lock:
            if agent_id not in self._agents:
                raise UnknownAgentError(
                        f"unknown agent id {agent_id!r} (runtime knows {len(self._agents)} agents)"
                    )
            return list(self._agents[agent_id].children)

    def is_settled(self, agent_id: str) -> bool:
        """True once *agent_id* has reached a terminal state."""
        with self._lock:
            if agent_id not in self._agents:
                raise UnknownAgentError(
                        f"unknown agent id {agent_id!r} (runtime knows {len(self._agents)} agents)"
                    )
            return is_terminal(self._agents[agent_id]._status)

    # -- read-only inspection helpers (W4.5) ---------------------------------
    # Public, read-only views over the runtime's private state so tests and
    # hosts can inspect the registry / stop flags / caps watchdog WITHOUT
    # reaching into privates. Each returns a COPY (or a value) the caller
    # cannot use to mutate the runtime. The privates stay functional; these
    # are additive, not a forced churn.

    def agents_snapshot(self) -> dict:
        """A read-only snapshot of the agent registry (id -> Agent).

        Returns a shallow COPY of the registry: mutating the returned dict
        (or the Agent objects it references) does NOT affect the runtime's
        registry. Use this instead of reading ``rt._agents`` directly.
        """
        with self._lock:
            return dict(self._agents)

    def is_stopped(self, agent_id: str) -> bool:
        """True once *agent_id*'s stop flag has been set.

        Read-only view of the per-agent stop flag (the same flag
        ``cancel``/``stop`` set). Raises
        :class:`~dhc.errors.UnknownAgentError` for an unknown id. Use this
        instead of reading ``rt._stop_flags`` directly.
        """
        with self._lock:
            if agent_id not in self._agents:
                raise UnknownAgentError(
                    f"unknown agent id {agent_id!r} (runtime knows {len(self._agents)} agents)"
                )
            return self._stop_flags[agent_id].is_set()

    def caps_state(self) -> dict:
        """A read-only view of the caps-watchdog per-agent cursor state.

        Returns a COPY of the message-rate watermark cursors
        (``agent_id -> int``) the watchdog uses to count per-step fresh
        events. Mutating the returned dict does NOT affect the watchdog.
        Use this instead of reading ``rt._caps_cursors`` directly.
        """
        with self._lock:
            return dict(self._caps_cursors)

    # -- directed messaging (the framework communication primitive, 0015) --

    def send(self, sender_id: str, recipient_id: str, body: str) -> Event:
        """Send a direct message from *sender_id* to *recipient_id*.

        The framework's communication primitive (decision 0015): direct
        agent-to-agent messaging is core; channel policies (rooms,
        escalation, operator questions) are tooling composed over it.
        Emits a *receiver-addressed* ``message_sent`` event on the
        recipient's own event stream, so the message rides the existing
        delivery pipeline — the recipient's digest, recent context, and
        ``events`` tool — with no channel installed. The event is
        persisted before delivery (bus discipline), FIFO-ordered, and
        bounded on the receiving side by the ``messages_per_step`` cap.

        *sender_id* is a free-form identity (an agent passes its id; the
        operator passes ``"operator"``). *recipient_id* must be a live
        agent. *body* is a short value — large content belongs in an
        artifact reference (context encapsulation).
        """
        with self._lock:
            if recipient_id not in self._agents:
                raise ChannelError(f"unknown recipient {recipient_id!r}")
        event = Event(
            kind=EventKind.message_sent,
            agent_id=recipient_id,
            payload={
                "sender_id": sender_id,
                "message_id": uuid.uuid4().hex,
                "body": body,
            },
        )
        self.event_bus.publish(f"events:{recipient_id}", event)
        return event

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
        context, the StateWriter poll thread). Returned events are
        boundary snapshots (deep copies) — payload mutation stays private
        to the reader.
        """
        topic = f"events:{agent_id}"
        peek = getattr(self.event_bus, "peek", None)
        if peek is None:
            # A bus without the fan-out seam: fall back to the destructive
            # drain (the pre-fix contract).
            return _crossing_snapshot(list(self.event_bus.drain(topic)))
        events = peek(topic)
        with self._lock:
            cursor = self._event_cursors.get(agent_id, 0)
            if len(events) < cursor:
                # The stream shrank underneath us (a foreign destructive
                # drain): re-read from the start rather than skip events.
                cursor = 0
            fresh = events[cursor:]
            self._event_cursors[agent_id] = len(events)
        return _crossing_snapshot(list(fresh))

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
        persisted, ordered stream. Returned events are boundary snapshots
        (deep copies) — payload mutation stays private to the reader.
        """
        topic = f"events:{agent_id}"
        peek = getattr(self.event_bus, "peek", None)
        if peek is None:
            # A bus without the fan-out seam: fall back to the destructive
            # drain (the pre-fix contract), same as :meth:`events`.
            return _crossing_snapshot(list(self.event_bus.drain(topic)))
        events = peek(topic)
        with self._lock:
            cursor = self._tool_event_cursors.get(agent_id, 0)
            if len(events) < cursor:
                # The stream shrank underneath us (a foreign destructive
                # drain): re-read from the start rather than skip events.
                cursor = 0
            fresh = events[cursor:]
            self._tool_event_cursors[agent_id] = len(events)
        return _crossing_snapshot(list(fresh))

    def completion_log(self) -> CompletionLog:
        """Return the at-most-once settlement registry."""
        return self._completion_log


# --------------------------------------------------------------------------- #
# The core surface registration (W1.2)
# --------------------------------------------------------------------------- #


def _register_core_surface() -> None:
    """Register the core runtime names in the surface registry (idempotent).

    The 13 action names every Runtime injects (plus the pump's yield
    vocabulary, which is prompt-visible as callables). The registry is
    metadata: the actual injection stays in ``_core_namespace``; this
    registration is what the prompt's API section and ``list_tools()``
    are generated from, and what the conformance test cross-checks.
    """
    for entry in (
        SurfaceEntry(
            name="agent",
            fn=None,
            doc="The agent facade: identity, accounting reads, actions.",
            tier="core",
            call="agent",
        ),
        SurfaceEntry(
            name="spawn",
            fn=WorkspaceAgent.spawn,
            doc="Spawn a child agent (non-blocking); return its handle.",
            tier="core",
            call="spawn(requirement, acceptance=(), driver=None, on_done=None)",
        ),
        SurfaceEntry(
            name="send",
            fn=WorkspaceAgent.send,
            doc="Direct message to another agent (the core primitive).",
            tier="core",
            call="send(recipient_id, body)",
        ),
        SurfaceEntry(
            name="complete",
            fn=WorkspaceAgent.complete,
            doc="Settle the agent as completed.",
            tier="core",
            call="complete(headline, artifacts=())",
        ),
        SurfaceEntry(
            name="fail",
            fn=WorkspaceAgent.fail,
            doc="Settle the agent as failed.",
            tier="core",
            call="fail(reason)",
        ),
        SurfaceEntry(
            name="record_result",
            fn=WorkspaceAgent.record_result,
            doc="Record a not-ok last result (does NOT cancel).",
            tier="core",
            call="record_result(reason)",
        ),
        SurfaceEntry(
            name="status",
            fn=WorkspaceAgent.status,
            doc="The agent's current status.",
            tier="core",
            call="status()",
        ),
        SurfaceEntry(
            name="result",
            fn=WorkspaceAgent.result,
            doc="The agent's current result.",
            tier="core",
            call="result()",
        ),
        SurfaceEntry(
            name="tool",
            fn=WorkspaceAgent.tool,
            doc="Run a callable, capturing its output as a ToolResult.",
            tier="core",
            call="tool(callable, *args)",
        ),
        SurfaceEntry(
            name="bash",
            fn=bash,
            doc="Run a shell command; return the captured output as text.",
            tier="core",
            call="bash(cmd)",
        ),
        SurfaceEntry(
            name="await_",
            fn=WorkspaceAgent.await_,
            doc="Block until the child settles; return its Completion.",
            tier="core",
            call="await_(handle)",
        ),
        SurfaceEntry(
            name="poll",
            fn=WorkspaceAgent.poll,
            doc="The child's current status (non-blocking).",
            tier="core",
            call="poll(handle)",
        ),
        SurfaceEntry(
            name="children_of",
            fn=WorkspaceAgent.children_of,
            doc="Handles of the agent's spawned children.",
            tier="core",
            call="children_of(handle)",
        ),
        SurfaceEntry(
            name="Await",
            fn=Await,
            doc="Yield vocabulary: block the runner until the child settles.",
            tier="advanced",
        ),
        SurfaceEntry(
            name="Poll",
            fn=Poll,
            doc="Yield vocabulary: check the child, then resume.",
            tier="advanced",
        ),
        SurfaceEntry(
            name="Sleep",
            fn=Sleep,
            doc="Yield vocabulary: pause the runner for a beat.",
            tier="advanced",
        ),
    ):
        default_registry.register(entry)


# The core surface is registered at import time (W1.2): the registry
# must be populated before any runtime exists — the prompt layer renders
# from it without holding a runtime instance.
_register_core_surface()
