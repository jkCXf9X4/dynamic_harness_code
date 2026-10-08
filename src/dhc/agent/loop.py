"""The agent worker loop (the LOOP concern, extracted from ``runtime.py``).

Owns the thread-body concern: ``pump_agent`` (the worker entry), the ONE
pumped loop that drives the agent-authored ``__runner`` generator one
yield-window per step, the legacy turn loop for non-pump engines, the
runner install seam, and the yield-servicing park/resume helpers. The
yield vocabulary (``Await`` / ``Poll`` / ``Sleep``, D3) lives here too —
it is part of the loop's in-code surface.

The four hard gates (D2) are enforced on the pump path exactly as before:

- settlement at-most-once (``Runtime._settle`` / CompletionLog — stays in
  ``runtime.py``),
- crash containment (per-step error/timeout classification),
- ceiling caps (``Runtime._caps_watchdog`` -> :mod:`dhc.agent.caps`),
- cancellation grace (stop-flag check between steps).

Shape: module-level functions taking the ``Runtime`` instance as first
param; ``runtime.py`` keeps thin method wrappers as the re-export seam, so
the moved bodies below call back through ``runtime.<name>`` exactly where
they used to call ``self.<name>`` — dynamic dispatch (and any monkeypatching
of the Runtime methods) is preserved. This module must never import
``runtime`` (one-way dependency: runtime -> loop).
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

from .agent import Agent
from ..errors import TurnTimeoutError
from ..llm.fabrication import DEFAULT_RUNNER_SOURCE, fabrication_kit
from ..data.models import AgentStatus, EventKind, Result, is_terminal
from . import integrity

#: Default step timeout for the pump when settings provide none (seconds).
_DEFAULT_STEP_TIMEOUT = 120.0


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
# Pump predicates
# --------------------------------------------------------------------------- #


def supports_pump(runtime: Any) -> bool:
    """True when the engine can drive a resumable ``__runner`` generator.

    The pumped path needs ``install``/``advance``/``inject``/``kill``
    (ReplEngine primitives, IMP-001 Step 1). A plain in-memory engine
    (or a bare ``Runtime()`` with no repl_engine) falls back to the
    legacy turn loop.
    """
    if getattr(runtime, "repl_engine", None) is not None:
        return True
    return hasattr(runtime.engine, "advance")


def step_timeout(runtime: Any) -> float:
    """The per-step timeout the pump passes to ``engine.advance``.

    Never None: a synchronous advance would let a runaway step hang the
    pump thread forever. Falls back to a sensible default when settings
    provide none.
    """
    return runtime._max_turn_seconds() or _DEFAULT_STEP_TIMEOUT


# --------------------------------------------------------------------------- #
# Worker entry
# --------------------------------------------------------------------------- #


def pump_agent(
    runtime: Any, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]
) -> None:
    """Drive *agent_id* to settlement (IMP-001 Step 3).

    Sets the agent running, then either runs the legacy turn loop (plain
    in-memory engine — the same default-fabrication semantics for the
    legacy engine) or the pumped loop (ReplEngine-backed runtime driving
    the agent-authored ``__runner`` generator one yield-window at a time
    under the four hard gates + caps watchdog). Any escape settles the
    agent failed (crash containment).
    """
    agent = runtime._agents[agent_id]
    agent._status = AgentStatus.running
    try:
        if not runtime._supports_pump():
            runtime._legacy_loop(agent_id, driver)
            return
        runtime._pump_loop(agent_id, driver)
    except Exception as exc:  # noqa: BLE001 - last-resort containment
        runtime._settle(agent_id, AgentStatus.failed, reason=f"worker crashed: {exc}")


def legacy_loop(
    runtime: Any, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]
) -> None:
    """The legacy turn loop (exact old ``_worker_loop`` body).

    Used only when the engine does not support resumable runners (plain
    ``_MemoryEngine`` / bare ``Runtime()``): decide -> execute -> settle,
    with the same crash/timeout/cancellation containment as before. This
    is NOT a second loop for agents on the real runtime — it is the same
    default-fabrication semantics for the legacy in-memory engine.
    """
    agent = runtime._agents[agent_id]
    last_result: Optional[Result] = None
    try:
        while True:
            if runtime._stop_flags[agent_id].is_set():
                runtime._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                return
            # Completion callbacks run between the parent's own actions,
            # in completion order (INFO-039/047).
            runtime._drain_completions(agent_id)
            if driver is None:
                code = None
            else:
                try:
                    code = driver(agent)
                except Exception as exc:  # noqa: BLE001 - crash containment
                    runtime._emit(
                        agent_id,
                        EventKind.crash,
                        payload={"error": f"{type(exc).__name__}: {exc}"},
                    )
                    runtime._settle(agent_id, AgentStatus.failed, reason=f"driver crashed: {exc}")
                    return
            if code is None:
                # Driver says settle. Parent liveness (INFO-014): a parent
                # must NOT settle while it has unsettled children.
                if not runtime._wait_children_settled(agent_id):
                    return  # cancelled while waiting
                runtime._drain_completions(agent_id)
                if runtime._stop_flags[agent_id].is_set():
                    runtime._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                    return
                if last_result is not None and last_result.ok:
                    runtime._settle(agent_id, AgentStatus.completed, summary=str(last_result.value or ""))
                else:
                    reason = last_result.reason if last_result is not None else "no result"
                    runtime._settle(agent_id, AgentStatus.failed, reason=reason)
                return
            # One turn: emit, execute, record.
            runtime._emit(agent_id, EventKind.turn_started, payload={"code": code})
            agent._last_result = None
            namespace = runtime._build_namespace(agent)
            try:
                runtime.engine.execute(
                    agent_id,
                    code,
                    namespace,
                    timeout=runtime._max_turn_seconds(),
                )
            except TurnTimeoutError as exc:
                runtime._emit(agent_id, EventKind.timeout, payload={"error": str(exc)})
                runtime._settle(agent_id, AgentStatus.timeout, reason=str(exc))
                return
            except Exception as exc:  # noqa: BLE001 - crash containment
                runtime._emit(
                    agent_id,
                    EventKind.turn_failed,
                    payload={"error": f"{type(exc).__name__}: {exc}"},
                )
                runtime._settle(agent_id, AgentStatus.failed, reason=f"turn crashed: {exc}")
                return
            last_result = agent._last_result
            if last_result is not None:
                runtime._emit(
                    agent_id,
                    EventKind.turn_completed,
                    payload={"ok": last_result.ok, "reason": last_result.reason},
                )
                # Acceptance check: non-empty acceptance + ok result -> settle.
                if agent.acceptance and last_result.ok:
                    runtime._settle(
                        agent_id,
                        AgentStatus.completed,
                        summary=str(last_result.value or ""),
                    )
                    return
            else:
                runtime._emit(
                    agent_id,
                    EventKind.turn_completed,
                    payload={"ok": True, "reason": ""},
                )
    except Exception as exc:  # noqa: BLE001 - last-resort containment
        runtime._settle(agent_id, AgentStatus.failed, reason=f"worker crashed: {exc}")


def pump_loop(
    runtime: Any, agent_id: str, driver: Optional[Callable[[Agent], Optional[str]]]
) -> None:
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
    engine = getattr(runtime, "repl_engine", None) or runtime.engine
    agent = runtime._agents[agent_id]
    kit = fabrication_kit(runtime, engine, agent)
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
    installed_source = runtime._install_runner(engine, agent_id, kit)

    step_count = 0
    started_ts = time.time()
    try:
        while True:
            # Cancellation grace (INFO-040): cancellation lands between
            # steps; the stop flag is the grace point. Kill the runner so
            # it is never resumed (advance returns "abandoned").
            if runtime._stop_flags[agent_id].is_set():
                try:
                    engine.kill(agent_id)
                except Exception:  # noqa: BLE001 - kill is best-effort
                    pass
                runtime._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                return
            # Completion callbacks run between the parent's own actions,
            # in completion order (INFO-039/047).
            runtime._drain_completions(agent_id)
            # Caps watchdog: ceiling caps are hard gates (D2). G-01: the
            # agent's working budgets (context.budgets) are min-clamped
            # onto the ceilings inside the predicate — the effective limit
            # is min(agent_budget, ceiling), evaluated here in pump code
            # (never in agent code), so an agent budget can only tighten a
            # limit, never loosen one (R3).
            hit = runtime._caps_hit(agent_id, engine, step_count, started_ts)
            if hit is not None:
                cap = hit["cap"]
                runtime._emit(
                    agent_id,
                    EventKind.crash,
                    payload={
                        "cap": cap,
                        "limit": hit["limit"],
                        "source": hit["source"],
                    },
                )
                try:
                    engine.kill(agent_id)
                except Exception:  # noqa: BLE001 - kill is best-effort
                    pass
                runtime._settle(
                    agent_id,
                    AgentStatus.failed,
                    reason=f"cap exceeded: {cap}",
                )
                return
            # IMP-001 Step 5 (D4): ensure the fabrication is intact
            # between steps. A broken/deleted fabrication (e.g.
            # ``__runner = 42``) is re-seeded here — before the runner is
            # advanced — so the agent continues instead of failing. The
            # re-seed emits a crash event with the reseeded names.
            integrity.ensure_fabrication(kit)
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
                installed_source = runtime._install_runner(engine, agent_id, kit, source)
            step_count += 1
            runtime._emit(agent_id, EventKind.turn_started, payload={"step": step_count})
            outcome = engine.advance(agent_id, timeout=runtime._step_timeout())
            if outcome.kind == "yield":
                value = outcome.value
                if isinstance(value, Await):
                    # D3: park the parent's runner until the child
                    # settles; the parent's step budget is NOT consumed
                    # while parked.
                    runtime._emit(
                        agent_id,
                        EventKind.turn_completed,
                        payload={"ok": True, "step": step_count, "yield": "await"},
                    )
                    if not runtime._service_await(agent_id, engine, value.handle):
                        try:
                            engine.kill(agent_id)
                        except Exception:  # noqa: BLE001 - kill is best-effort
                            pass
                        runtime._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                        return
                    continue
                if isinstance(value, Sleep):
                    runtime._emit(
                        agent_id,
                        EventKind.turn_completed,
                        payload={"ok": True, "step": step_count, "yield": "sleep"},
                    )
                    if not runtime._service_sleep(agent_id, engine, value.seconds):
                        try:
                            engine.kill(agent_id)
                        except Exception:  # noqa: BLE001 - kill is best-effort
                            pass
                        runtime._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
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
                    status = runtime.poll(getattr(value.handle, "id", value.handle))
                    kit["state"]["yield_result"] = status
                    engine.inject(agent_id, {"yield_result": status})
                    runtime._emit(
                        agent_id,
                        EventKind.turn_completed,
                        payload={"ok": True, "step": step_count, "yield": "poll"},
                    )
                    continue
                runtime._emit(
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
                        runtime._settle(
                            agent_id,
                            AgentStatus.completed,
                            summary=str(last_result.value or ""),
                        )
                    else:
                        reason = last_result.reason if last_result is not None else "no result"
                        runtime._settle(agent_id, AgentStatus.failed, reason=reason)
                return
            if outcome.kind == "timeout":
                # The engine already rolled back the workspace and
                # abandoned the runner (never resumed). Runaway contained.
                if runtime._stop_flags[agent_id].is_set():
                    # Cancelled while mid-step: the step timeout bounded
                    # it; the engine rolled back + abandoned. Settle
                    # cancelled (cancellation grace, INFO-040).
                    try:
                        engine.kill(agent_id)
                    except Exception:  # noqa: BLE001 - kill is best-effort
                        pass
                    runtime._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                    return
                runtime._emit(
                    agent_id,
                    EventKind.timeout,
                    payload={"error": outcome.reason or "step timed out"},
                )
                runtime._settle(
                    agent_id,
                    AgentStatus.timeout,
                    reason=outcome.reason or "step timed out",
                )
                return
            if outcome.kind == "error":
                if runtime._stop_flags[agent_id].is_set():
                    # Cancelled while mid-step: the step raised; settle
                    # cancelled (cancellation grace, INFO-040).
                    try:
                        engine.kill(agent_id)
                    except Exception:  # noqa: BLE001 - kill is best-effort
                        pass
                    runtime._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                    return
                runtime._emit(
                    agent_id,
                    EventKind.turn_failed,
                    payload={"error": outcome.reason or "step failed"},
                )
                runtime._settle(
                    agent_id,
                    AgentStatus.failed,
                    reason=outcome.reason or "step failed",
                )
                return
            # suspended / abandoned / not_installed: the runner is not
            # advancing. If cancelled, settle cancelled; otherwise try to
            # re-seed the fabrication and continue, or settle failed.
            if runtime._stop_flags[agent_id].is_set():
                try:
                    engine.kill(agent_id)
                except Exception:  # noqa: BLE001 - kill is best-effort
                    pass
                runtime._settle(agent_id, AgentStatus.cancelled, reason="cancelled")
                return
            reseeded = integrity.reseed_fabrication(kit)
            if reseeded:
                continue
            runtime._settle(
                agent_id,
                AgentStatus.failed,
                reason=f"runner unavailable: {outcome.kind}",
            )
            return
    except Exception as exc:  # noqa: BLE001 - last-resort containment
        runtime._settle(agent_id, AgentStatus.failed, reason=f"worker crashed: {exc}")


# --------------------------------------------------------------------------- #
# Runner install / yield servicing
# --------------------------------------------------------------------------- #


def install_runner(
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


def service_await(runtime: Any, agent_id: str, engine: Any, handle: Any) -> bool:
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
            if runtime._stop_flags[agent_id].is_set():
                return False
            runtime._drain_completions(agent_id)
            try:
                status = runtime.poll(child_id)
            except KeyError:
                # The awaited agent vanished (should not happen); treat it
                # as settled so the parent does not hang.
                return True
            if is_terminal(status):
                return True
            time.sleep(0.01)
    finally:
        engine.resume(agent_id)


def service_sleep(runtime: Any, agent_id: str, engine: Any, seconds: float) -> bool:
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
            if runtime._stop_flags[agent_id].is_set():
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return True
            time.sleep(min(0.01, remaining))
    finally:
        engine.resume(agent_id)
