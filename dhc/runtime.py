"""The runtime orchestrator.

Owns the agent registry, thread-per-agent placement (INFO-038), the worker
loop (driver -> turn -> settle), completion dispatch (at-most-once, INFO-046),
parent liveness (INFO-014), and cancellation (INFO-034/040).

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
from .errors import ChannelError, TurnError, TurnTimeoutError
from .models import (
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
                target=self._worker_loop,
                args=(agent_id, driver),
                name=f"dhc-agent-{agent_id}",
                daemon=True,
            )
            self._threads[agent_id] = thread
            thread.start()
        return self._handles[agent_id]

    # -- worker loop ---------------------------------------------------------

    def _worker_loop(self, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]) -> None:
        agent = self._agents[agent_id]
        agent._status = AgentStatus.running
        last_result: Optional[Result] = None
        try:
            while True:
                if self._stop_flags[agent_id].is_set():
                    self._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                    return
                # Completion callbacks run between the parent's own actions,
                # in completion order (INFO-039/047).
                self._drain_completions(agent_id)
                if driver is None:
                    code = None
                else:
                    try:
                        code = driver(agent)
                    except Exception as exc:  # noqa: BLE001 - crash containment
                        self._emit(
                            agent_id,
                            EventKind.crash,
                            payload={"error": f"{type(exc).__name__}: {exc}"},
                        )
                        self._settle(agent_id, AgentStatus.failed, reason=f"driver crashed: {exc}")
                        return
                if code is None:
                    # Driver says settle. Parent liveness (INFO-014): a parent
                    # must NOT settle while it has unsettled children.
                    if not self._wait_children_settled(agent_id):
                        return  # cancelled while waiting
                    self._drain_completions(agent_id)
                    if self._stop_flags[agent_id].is_set():
                        self._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                        return
                    if last_result is not None and last_result.ok:
                        self._settle(agent_id, AgentStatus.completed, summary=str(last_result.value or ""))
                    else:
                        reason = last_result.reason if last_result is not None else "no result"
                        self._settle(agent_id, AgentStatus.failed, reason=reason)
                    return
                # One turn: emit, execute, record.
                self._emit(agent_id, EventKind.turn_started, payload={"code": code})
                agent._last_result = None
                namespace = self._build_namespace(agent)
                try:
                    self.engine.execute(
                        agent_id,
                        code,
                        namespace,
                        timeout=self._max_turn_seconds(),
                    )
                except TurnTimeoutError as exc:
                    self._emit(agent_id, EventKind.timeout, payload={"error": str(exc)})
                    self._settle(agent_id, AgentStatus.timeout, reason=str(exc))
                    return
                except Exception as exc:  # noqa: BLE001 - crash containment
                    self._emit(
                        agent_id,
                        EventKind.turn_failed,
                        payload={"error": f"{type(exc).__name__}: {exc}"},
                    )
                    self._settle(agent_id, AgentStatus.failed, reason=f"turn crashed: {exc}")
                    return
                last_result = agent._last_result
                if last_result is not None:
                    self._emit(
                        agent_id,
                        EventKind.turn_completed,
                        payload={"ok": last_result.ok, "reason": last_result.reason},
                    )
                    # Acceptance check: non-empty acceptance + ok result -> settle.
                    if agent.acceptance and last_result.ok:
                        self._settle(
                            agent_id,
                            AgentStatus.completed,
                            summary=str(last_result.value or ""),
                        )
                        return
                else:
                    self._emit(
                        agent_id,
                        EventKind.turn_completed,
                        payload={"ok": True, "reason": ""},
                    )
        except Exception as exc:  # noqa: BLE001 - last-resort containment
            self._settle(agent_id, AgentStatus.failed, reason=f"worker crashed: {exc}")

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
        """Return the events emitted by *agent_id*, in order."""
        return list(self.event_bus.drain(f"events:{agent_id}"))

    def completion_log(self) -> CompletionLog:
        """Return the at-most-once settlement registry."""
        return self._completion_log