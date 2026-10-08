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
from .fabrication import DEFAULT_RUNNER_SOURCE, fabrication_kit
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

#: Default step timeout for the pump when settings provide none (seconds).
_DEFAULT_STEP_TIMEOUT = 120.0
#: Caps watchdog defaults (overridable via settings; Step 5 owns full config).
_DEFAULT_TIMEOUT_SECONDS = 7200.0
_DEFAULT_MAX_ITERATIONS = 400
_DEFAULT_MAX_CHILDREN = 32
_DEFAULT_MAX_WORKSPACE_BYTES = 1 << 20  # 1 MiB
#: Message-rate cap is disabled by default (no config field yet; Step 5's
#: job). Enforced only when settings provide ``max_messages_per_step``.
_DEFAULT_MAX_MESSAGES_PER_STEP = None


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
# Yield vocabulary (IMP-001 Step 4, D3: yield-async split)
# --------------------------------------------------------------------------- #


class Await:
    """Yield request: park the parent's runner until *handle*'s agent settles.

    The parent's runner is NOT advanced while parked (D3): the parent's step
    budget is not consumed. *handle* is an ``AgentHandle`` (or anything with
    ``.id``, ``.poll() -> AgentStatus`` and ``.await_() -> Completion``).
    """

    __slots__ = ("handle",)

    def __init__(self, handle: Any) -> None:
        self.handle = handle


class Poll:
    """Yield request: return *handle*'s current ``AgentStatus`` without blocking.

    The pump delivers the status back into the generator under the well-known
    name ``yield_result`` (workspace) and ``state["yield_result"]`` (the
    runner's ctx slot) before the runner is advanced again.
    """

    __slots__ = ("handle",)

    def __init__(self, handle: Any) -> None:
        self.handle = handle


class Sleep:
    """Yield request: park the parent's runner for *seconds* (stop-flag aware).

    The parent's runner is NOT advanced while parked (D3): the parent's step
    budget is not consumed.
    """

    __slots__ = ("seconds",)

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds


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
                target=self._pump_agent,
                args=(agent_id, driver),
                name=f"dhc-agent-{agent_id}",
                daemon=True,
            )
            self._threads[agent_id] = thread
            thread.start()
        return self._handles[agent_id]

    # -- worker loop ---------------------------------------------------------

    def _supports_pump(self) -> bool:
        """True when the engine can drive a resumable ``__runner`` generator.

        The pumped path needs ``install``/``advance``/``inject``/``kill``
        (ReplEngine primitives, IMP-001 Step 1). A plain in-memory engine
        (or a bare ``Runtime()`` with no repl_engine) falls back to the
        legacy turn loop.
        """
        if getattr(self, "repl_engine", None) is not None:
            return True
        return hasattr(self.engine, "advance")

    def _step_timeout(self) -> float:
        """The per-step timeout the pump passes to ``engine.advance``.

        Never None: a synchronous advance would let a runaway step hang the
        pump thread forever. Falls back to a sensible default when settings
        provide none.
        """
        return self._max_turn_seconds() or _DEFAULT_STEP_TIMEOUT

    def _pump_agent(self, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]) -> None:
        """Drive *agent_id* to settlement (IMP-001 Step 3).

        Sets the agent running, then either runs the legacy turn loop (plain
        in-memory engine — the same default-fabrication semantics for the
        legacy engine) or the pumped loop (ReplEngine-backed runtime driving
        the agent-authored ``__runner`` generator one yield-window at a time
        under the four hard gates + caps watchdog). Any escape settles the
        agent failed (crash containment).
        """
        agent = self._agents[agent_id]
        agent._status = AgentStatus.running
        try:
            if not self._supports_pump():
                self._legacy_loop(agent_id, driver)
                return
            self._pump_loop(agent_id, driver)
        except Exception as exc:  # noqa: BLE001 - last-resort containment
            self._settle(agent_id, AgentStatus.failed, reason=f"worker crashed: {exc}")

    def _legacy_loop(self, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]) -> None:
        """The legacy turn loop (exact old ``_worker_loop`` body).

        Used only when the engine does not support resumable runners (plain
        ``_MemoryEngine`` / bare ``Runtime()``): decide -> execute -> settle,
        with the same crash/timeout/cancellation containment as before. This
        is NOT a second loop for agents on the real runtime — it is the same
        default-fabrication semantics for the legacy in-memory engine.
        """
        agent = self._agents[agent_id]
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

    def _pump_loop(self, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]) -> None:
        """The pumped path: drive the agent's ``__runner`` one step at a time.

        Installs the fabrication kit (default ``__runner`` + decide + context)
        into the engine workspace, then advances the runner one yield-window
        per iteration under the four hard gates:

        - settlement at-most-once (``_settle`` / CompletionLog),
        - crash containment (per-step error/timeout classification),
        - ceiling caps (``_caps_watchdog``),
        - cancellation grace (stop-flag check between steps).

        A custom spawn-time *driver* is honored by seeding
        ``state["_driver"]`` BEFORE installing — the decide fabrication reads
        it, which is the seam that makes ScriptedDriver/MockDriver work
        through the pump.
        """
        engine = getattr(self, "repl_engine", None) or self.engine
        agent = self._agents[agent_id]
        kit = fabrication_kit(self, engine, agent)
        if driver is not None:
            kit["state"]["_driver"] = driver
        # The yield vocabulary (D3) is part of the in-code surface: agent
        # code and agent-authored runners can `yield Await(c1)` etc. The kit
        # doubles as the runner's ctx. NOTE: the kit must NOT be merged with
        # _build_namespace here — the wired namespace (wiring.py) injects a
        # FRESH fabrication kit (fresh state dict, __runner=DEFAULT), which
        # would clobber the seeded _driver and the kit's state.
        kit["Await"] = Await
        kit["Poll"] = Poll
        kit["Sleep"] = Sleep
        engine.inject(agent_id, kit)
        installed_source = self._install_runner(engine, agent_id, kit)

        step_count = 0
        started_ts = time.time()
        try:
            while True:
                # Cancellation grace (INFO-040): cancellation lands between
                # steps; the stop flag is the grace point. Kill the runner so
                # it is never resumed (advance returns "abandoned").
                if self._stop_flags[agent_id].is_set():
                    try:
                        engine.kill(agent_id)
                    except Exception:  # noqa: BLE001 - kill is best-effort
                        pass
                    self._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                    return
                # Completion callbacks run between the parent's own actions,
                # in completion order (INFO-039/047).
                self._drain_completions(agent_id)
                # Caps watchdog: ceiling caps are hard gates (D2).
                cap = self._caps_watchdog(agent_id, engine, step_count, started_ts)
                if cap is not None:
                    self._emit(
                        agent_id,
                        EventKind.crash,
                        payload={"cap": cap, "limit": self._cap_limit(cap)},
                    )
                    try:
                        engine.kill(agent_id)
                    except Exception:  # noqa: BLE001 - kill is best-effort
                        pass
                    self._settle(
                        agent_id,
                        AgentStatus.failed,
                        reason=f"cap exceeded: {cap}",
                    )
                    return
                # Custom-runner seam: an agent that replaced the workspace
                # `__runner` source string gets its own runner compiled from
                # that source. Re-install only when the source changed AND is
                # not the default source: the wired namespace re-injects the
                # default `__runner` on every run_block, so a custom runner
                # that calls run_block must NOT be replaced by the default
                # runner (we are between steps here, so the runner is never
                # parked).
                source = engine.globals_for(agent_id).get("__runner")
                if (
                    isinstance(source, str)
                    and source != installed_source
                    and source != DEFAULT_RUNNER_SOURCE
                ):
                    installed_source = self._install_runner(engine, agent_id, kit, source)
                step_count += 1
                self._emit(agent_id, EventKind.turn_started, payload={"step": step_count})
                outcome = engine.advance(agent_id, timeout=self._step_timeout())
                if outcome.kind == "yield":
                    value = outcome.value
                    if isinstance(value, Await):
                        # D3: park the parent's runner until the child
                        # settles; the parent's step budget is NOT consumed
                        # while parked.
                        self._emit(
                            agent_id,
                            EventKind.turn_completed,
                            payload={"ok": True, "step": step_count, "yield": "await"},
                        )
                        if not self._service_await(agent_id, engine, value.handle):
                            try:
                                engine.kill(agent_id)
                            except Exception:  # noqa: BLE001 - kill is best-effort
                                pass
                            self._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                            return
                        continue
                    if isinstance(value, Sleep):
                        self._emit(
                            agent_id,
                            EventKind.turn_completed,
                            payload={"ok": True, "step": step_count, "yield": "sleep"},
                        )
                        if not self._service_sleep(agent_id, engine, value.seconds):
                            try:
                                engine.kill(agent_id)
                            except Exception:  # noqa: BLE001 - kill is best-effort
                                pass
                            self._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                            return
                        continue
                    if isinstance(value, Poll):
                        # Non-blocking: deliver the child's current status
                        # back INTO the generator. No "send value back"
                        # primitive exists, so the result is injected under
                        # the well-known name `yield_result` (workspace) and
                        # `state["yield_result"]` (the runner's ctx slot).
                        # The handle may be an AgentHandle or an Agent (spawn
                        # returns the Agent); both carry `.id`.
                        status = self.poll(getattr(value.handle, "id", value.handle))
                        kit["state"]["yield_result"] = status
                        engine.inject(agent_id, {"yield_result": status})
                        self._emit(
                            agent_id,
                            EventKind.turn_completed,
                            payload={"ok": True, "step": step_count, "yield": "poll"},
                        )
                        continue
                    self._emit(
                        agent_id,
                        EventKind.turn_completed,
                        payload={"ok": True, "step": step_count},
                    )
                    continue
                if outcome.kind == "finished":
                    # The runner returned (settle() was called inside, or
                    # StopIteration). Settle by the last result if not already
                    # terminal (at-most-once).
                    if not is_terminal(agent._status):
                        last_result = agent._last_result
                        if last_result is not None and last_result.ok:
                            self._settle(
                                agent_id,
                                AgentStatus.completed,
                                summary=str(last_result.value or ""),
                            )
                        else:
                            reason = last_result.reason if last_result is not None else "no result"
                            self._settle(agent_id, AgentStatus.failed, reason=reason)
                    return
                if outcome.kind == "timeout":
                    # The engine already rolled back the workspace and
                    # abandoned the runner (never resumed). Runaway contained.
                    if self._stop_flags[agent_id].is_set():
                        # Cancelled while mid-step: the step timeout bounded
                        # it; the engine rolled back + abandoned. Settle
                        # cancelled (cancellation grace, INFO-040).
                        try:
                            engine.kill(agent_id)
                        except Exception:  # noqa: BLE001 - kill is best-effort
                            pass
                        self._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                        return
                    self._emit(
                        agent_id,
                        EventKind.timeout,
                        payload={"error": outcome.reason or "step timed out"},
                    )
                    self._settle(
                        agent_id,
                        AgentStatus.timeout,
                        reason=outcome.reason or "step timed out",
                    )
                    return
                if outcome.kind == "error":
                    if self._stop_flags[agent_id].is_set():
                        # Cancelled while mid-step: the step raised; settle
                        # cancelled (cancellation grace, INFO-040).
                        try:
                            engine.kill(agent_id)
                        except Exception:  # noqa: BLE001 - kill is best-effort
                            pass
                        self._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                        return
                    self._emit(
                        agent_id,
                        EventKind.turn_failed,
                        payload={"error": outcome.reason or "step failed"},
                    )
                    self._settle(
                        agent_id,
                        AgentStatus.failed,
                        reason=outcome.reason or "step failed",
                    )
                    return
                # suspended / abandoned / not_installed: the runner is not
                # advancing. If cancelled, settle cancelled; otherwise try to
                # re-seed the fabrication and continue, or settle failed.
                if self._stop_flags[agent_id].is_set():
                    try:
                        engine.kill(agent_id)
                    except Exception:  # noqa: BLE001 - kill is best-effort
                        pass
                    self._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                    return
                try:
                    reseeded = kit["ensure_fabrication"]()
                except Exception:  # noqa: BLE001 - re-seed is best-effort
                    reseeded = []
                if reseeded:
                    continue
                self._settle(
                    agent_id,
                    AgentStatus.failed,
                    reason=f"runner unavailable: {outcome.kind}",
                )
                return
        except Exception as exc:  # noqa: BLE001 - last-resort containment
            self._settle(agent_id, AgentStatus.failed, reason=f"worker crashed: {exc}")

    def _install_runner(
        self,
        engine: Any,
        agent_id: str,
        kit: dict,
        source: Optional[str] = None,
    ) -> str:
        """Compile and install the agent's ``__runner`` generator.

        The source defaults to the kit's ``__runner`` (the default runner
        source injected by the fabrication kit). The runner is compiled with
        the workspace surface + kit as globals — so agent-authored runners can
        reference in-code names (``spawn``, ``complete``, ``Await``, ...)
        directly — and receives the kit as its ``ctx`` argument. Returns the
        installed source (the re-install seam compares it with the workspace
        ``__runner`` string).
        """
        if source is None:
            source = kit.get("__runner")
        if not isinstance(source, str):
            source = DEFAULT_RUNNER_SOURCE
        ns: dict = {"__builtins__": __builtins__}
        ns.update(engine.globals_for(agent_id))
        ns.update(kit)
        exec(compile(source, f"<runner:{agent_id}>", "exec"), ns)
        engine.install(agent_id, ns["__runner__"](kit))
        return source

    def _service_await(self, agent_id: str, engine: Any, handle: Any) -> bool:
        """Park *agent_id*'s runner until *handle*'s agent settles, then resume.

        The parent's runner is NOT advanced while parked (D3): step_count does
        not increment and the step budget is not consumed. Completion wakeups
        ride the existing CompletionDispatcher (INFO-047): the parent's
        pending completions are drained each poll so the parent's stream keeps
        moving while it waits.

        Returns True when the runner was resumed; False when the parent was
        cancelled while parked (the caller must kill the runner and settle).
        """
        engine.suspend(agent_id)
        # The handle may be an AgentHandle or an Agent (spawn returns the
        # Agent); both carry `.id`. Poll via the runtime so either works.
        child_id = getattr(handle, "id", handle)
        try:
            while True:
                if self._stop_flags[agent_id].is_set():
                    return False
                self._drain_completions(agent_id)
                try:
                    status = self.poll(child_id)
                except KeyError:
                    # The awaited agent vanished (should not happen); treat it
                    # as settled so the parent does not hang.
                    return True
                if is_terminal(status):
                    return True
                time.sleep(0.01)
        finally:
            engine.resume(agent_id)

    def _service_sleep(self, agent_id: str, engine: Any, seconds: float) -> bool:
        """Park *agent_id*'s runner for *seconds* (honoring the stop flag).

        The parent's runner is NOT advanced while parked (D3): step_count does
        not increment and the step budget is not consumed.

        Returns True when the runner was resumed; False when the parent was
        cancelled while parked (the caller must kill the runner and settle).
        """
        engine.suspend(agent_id)
        try:
            deadline = time.monotonic() + seconds
            while True:
                if self._stop_flags[agent_id].is_set():
                    return False
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return True
                time.sleep(min(0.01, remaining))
        finally:
            engine.resume(agent_id)

    def _cap(self, name: str, default: Any) -> Any:
        """Read a cap from settings None-safely (safety config first)."""
        s = self.settings
        if s is None:
            return default
        safety = getattr(getattr(s, "config", None), "safety", None)
        if safety is not None:
            value = getattr(safety, name, None)
            if value is not None:
                return value
        return getattr(s, name, default)

    def _cap_limit(self, cap: str) -> Any:
        """The configured limit for a cap name (for the crash event payload)."""
        return {
            "wall_clock": self._cap("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS),
            "iterations": self._cap("max_iterations", _DEFAULT_MAX_ITERATIONS),
            "children": self._cap("max_agents", _DEFAULT_MAX_CHILDREN),
            "workspace_bytes": self._cap("max_workspace_bytes", _DEFAULT_MAX_WORKSPACE_BYTES),
            "messages_per_step": self._cap("max_messages_per_step", _DEFAULT_MAX_MESSAGES_PER_STEP),
        }.get(cap)

    def _caps_watchdog(
        self,
        agent_id: str,
        engine: Any,
        step_count: int,
        started_ts: float,
    ) -> Optional[str]:
        """Return the name of the first ceiling cap exceeded, else None.

        Reads caps from settings None-safely (safety.timeout_seconds /
        max_iterations / max_agents; workspace bytes and message rate from
        module constants unless settings provide them). Tests force caps via
        a tiny settings object.
        """
        # Wall clock (safety.timeout_seconds).
        timeout_seconds = self._cap("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
        if timeout_seconds is not None and time.time() - started_ts > timeout_seconds:
            return "wall_clock"
        # Step count (safety.max_iterations).
        max_iterations = self._cap("max_iterations", _DEFAULT_MAX_ITERATIONS)
        if max_iterations is not None and step_count >= max_iterations:
            return "iterations"
        # Child count (safety.max_agents, or a per-agent constant).
        max_agents = self._cap("max_agents", _DEFAULT_MAX_CHILDREN)
        if max_agents is not None:
            with self._lock:
                child_count = len(self._agents[agent_id].children)
            if child_count >= max_agents:
                return "children"
        # Workspace bytes (module constant unless settings provide one).
        max_workspace_bytes = self._cap("max_workspace_bytes", _DEFAULT_MAX_WORKSPACE_BYTES)
        if max_workspace_bytes is not None:
            try:
                ws = engine.globals_for(agent_id)
                size = sum(len(str(v)) for v in ws.values())
            except Exception:  # noqa: BLE001 - sizing is best-effort
                size = 0
            if size > max_workspace_bytes:
                return "workspace_bytes"
        # Message rate (module constant unless settings provide one).
        max_messages = self._cap("max_messages_per_step", _DEFAULT_MAX_MESSAGES_PER_STEP)
        if max_messages is not None:
            try:
                pending = len(self.event_bus.drain(f"events:{agent_id}"))
            except Exception:  # noqa: BLE001 - counting is best-effort
                pending = 0
            if pending > max_messages:
                return "messages_per_step"
        return None

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
        """Return the events emitted by *agent_id*, in order."""
        return list(self.event_bus.drain(f"events:{agent_id}"))

    def completion_log(self) -> CompletionLog:
        """Return the at-most-once settlement registry."""
        return self._completion_log