"""Per-agent persistent REPL engine (INFO-050).

Each agent owns a private, persistent workspace — a plain ``dict`` used as the
``globals`` of every ``exec`` of that agent's code. Variables, functions and
imports defined in one turn are visible in the next, and are never shared with
other agents (INFO-050 isolation). Execution is serialized per agent: a second
``execute`` on the same agent blocks until the running turn finishes (INFO-050:
never concurrently). A turn that raises is contained (INFO-005): the failure is
returned as a failed :class:`~dhc.models.Result` and the workspace is
preserved. A turn that exceeds its timeout is contained (INFO-020): it returns
a failed result without hanging, and the workspace is rolled back to a snapshot
taken at turn start so a still-running worker thread can never corrupt it.

Resumable-run primitives (IMP-001 Step 1): an agent may also install a
resumable generator as its ``__runner`` and advance it one yield-window (one
step) at a time via :meth:`ReplEngine.advance`. Each timed advance snapshots
the workspace; on timeout the step is rolled back and the generator is
abandoned (never resumed). ``run_block`` provides non-locking nested exec so a
generator step can run code against the workspace without deadlocking on the
per-agent lock.

Rollback snapshots copy nested plain ``dict``/``list``/``tuple``/``set``
values (other objects stay shared by reference), so one snapshot per
in-flight turn costs memory proportional to the workspace's plain-container
size — the price of rolling back in-place nested mutation.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..data.models import Result


class TurnCancelled(BaseException):
    """Raised at a block boundary inside a turn that was cancelled.

    Subclasses :class:`BaseException` so ordinary ``except Exception`` in
    agent code does not swallow it; the engine turns it into a cancelled
    outcome and the pump settles the agent ``cancelled``.
    """


#: Granularity (seconds) at which a timed step polls its cancel predicate.
_CANCEL_POLL = 0.05

#: Per-thread cancel predicate for the in-code surface (``bash`` polls it).
_cancel_local = threading.local()


def cancel_requested() -> bool:
    """True when the turn running on this thread has been cancelled."""
    predicate = getattr(_cancel_local, "predicate", None)
    return bool(predicate is not None and predicate())


def _set_thread_cancel(predicate: Callable[[], bool] | None) -> None:
    _cancel_local.predicate = predicate


def _snapshot_value(value: Any) -> Any:
    """Copy nested plain containers; leave every other object by reference."""
    kind = type(value)
    if kind is dict:
        return {k: _snapshot_value(v) for k, v in value.items()}
    if kind is list:
        return [_snapshot_value(v) for v in value]
    if kind is tuple:
        return tuple(_snapshot_value(v) for v in value)
    if kind is set:
        return {_snapshot_value(v) for v in value}
    return value


def _snapshot_workspace(workspace: dict) -> dict:
    """Turn-start rollback snapshot (nested plain containers are copied).

    ``__builtins__`` is kept by reference: it is interpreter machinery, not
    agent state, and copying it would cost a dict of every builtin per turn.
    """
    snapshot = {}
    for name, value in workspace.items():
        if name == "__builtins__":
            snapshot[name] = value
            continue
        try:
            snapshot[name] = _snapshot_value(value)
        except Exception:  # noqa: BLE001 - a racy/odd value stays shared
            snapshot[name] = value
    return snapshot


@dataclass(frozen=True)
class AdvanceOutcome:
    """Outcome of one :meth:`ReplEngine.advance` call.

    ``kind`` is one of:

    - ``"yield"`` — the runner yielded ``value`` and remains active.
    - ``"finished"`` — the runner raised StopIteration; it is done.
    - ``"timeout"`` — the step exceeded its timeout; the runner was abandoned
      and the workspace was rolled back to the per-advance snapshot.
    - ``"cancelled"`` — the step observed a cancel request; the runner was
      abandoned and the workspace was rolled back to the per-advance
      snapshot.
    - ``"error"`` — the step raised; the runner is finished (a generator that
      raised cannot be resumed) and the workspace is preserved (INFO-005).
    - ``"suspended"`` — the runner is parked; advance did not run it.
    - ``"abandoned"`` — the runner was previously abandoned (timeout or kill);
      it is never resumed.
    - ``"not_installed"`` — no runner is installed for the agent.
    """

    kind: str
    value: Any = None
    reason: str = ""


class ReplEngine:
    """Per-agent persistent REPL.

    Public API
    ----------
    - ``execute(agent_id, code, namespace=None, timeout=None) -> Result``
    - ``install(agent_id, generator) -> None``
    - ``advance(agent_id, timeout=None) -> AdvanceOutcome``
    - ``inject(agent_id, namespace) -> None``
    - ``suspend(agent_id) -> None``
    - ``resume(agent_id) -> None``
    - ``kill(agent_id) -> None``
    - ``run_block(agent_id, code) -> Result``
    - ``reset(agent_id) -> None``
    - ``globals_for(agent_id) -> dict``
    - ``has_workspace(agent_id) -> bool``

    Design notes
    ------------
    - **Workspace**: one globals ``dict`` per agent, created lazily on first
      execute and kept until :meth:`reset`. Each turn runs
      ``exec(code, workspace)`` against that dict, so state persists across
      turns.
    - **Namespace injection**: the caller's namespace (the in-code surface:
      agent handle, publish, spawn, bash, room, ...) is merged into the
      workspace before each turn — caller values win over stale workspace
      values. Merged values stay in the workspace; the caller refreshes them
      every turn anyway.
    - **Result slot**: the workspace variable ``result`` is the per-turn output
      slot. It is cleared before each turn (a stale result from a previous turn
      is never returned) and restored if the turn fails, so a failed turn does
      not destroy state. After a successful turn, if ``result`` holds a
      :class:`~dhc.models.Result` it is returned; otherwise a default
      ``Result(done=True, ok=True, value=None)`` is returned.
    - **Serialization**: one :class:`threading.Lock` per agent; a second
      execute on the same agent **blocks** until the running turn finishes
      (blocking chosen over raising: the runtime's worker actions and
      completion callbacks must be able to queue on the same agent).
    - **Timeout containment**: with a timeout, the turn runs in a daemon worker
      thread and the caller ``join(timeout)``s it. On timeout the workspace is
      rolled back to a snapshot taken at turn start and a failed result with
      ``reason="turn timed out"`` is returned. The worker thread cannot be
      killed (Python threads are not killable) and may keep running in the
      background, but it only ever mutates the discarded pre-rollback dict
      (and the snapshot's own nested copies), so the workspace stays usable
      and uncorrupted. The snapshot copies nested plain containers (dict,
      list, tuple, set) so in-place mutation of a nested object by a
      timed-out turn is rolled back too; arbitrary objects stay shared by
      reference.

    Resumable-run primitives (IMP-001 Step 1)
    -----------------------------------------
    - **Runner**: :meth:`install` registers a resumable generator as the
      agent's ``__runner`` (engine-side; the workspace-citizen exposure lands
      with the fabrication kit in Step 2). :meth:`advance` runs one
      yield-window (one step) under the per-agent lock and returns an
      :class:`AdvanceOutcome` describing what the generator yielded.
    - **Per-advance snapshot**: each timed advance snapshots the workspace
      (nested plain containers copied, other objects by reference). On
      timeout the workspace is rolled back to the snapshot and the generator
      is **abandoned** — never resumed, because the old worker thread may
      still be mutating the discarded snapshot dict. Sequential join-ordered
      advances are safe.
    - **Cancellation**: :meth:`bind_cancel` attaches an external predicate
      (the pump binds the runtime's stop flag) and :meth:`request_cancel`
      sets the engine's own flag. A running turn observes it between blocks
      (:meth:`run_block` raises :class:`TurnCancelled`) and inside
      :meth:`advance`'s join loop, which abandons the runner and reports a
      ``"cancelled"`` outcome instead of waiting for the step timeout. A
      turn blocked in pure Python cannot be interrupted; it is abandoned
      exactly like a timed-out step.
    - **Lifecycle**: :meth:`suspend` parks the runner (advance does not run
      it), :meth:`resume` continues it from the same point, :meth:`kill`
      abandons it and clears the installed runner. Cancellation lands between
      steps (INFO-040).
    - **Nested exec reentrancy**: :meth:`run_block` executes a code block
      against the workspace WITHOUT taking the per-agent lock (the pump
      already holds it during an advance), so a nested ``run_block`` from
      inside a generator step does not deadlock. A runaway nested block is
      caught only by the outer step timeout; ``run_block`` takes no timeout
      of its own (a nested timeout would be unenforced — the outer step
      timeout is the only bound).
    """

    def __init__(self) -> None:
        self._workspaces: dict[str, dict] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._runners: dict[str, Any] = {}
        self._runner_states: dict[str, str] = {}
        self._cancel_events: dict[str, threading.Event] = {}
        self._cancel_predicates: dict[str, Callable[[], bool]] = {}
        self._dict_lock = threading.Lock()

    # -- public API -------------------------------------------------------- #

    def execute(
        self,
        agent_id: str,
        code: str,
        namespace: dict | None = None,
        timeout: float | None = None,
    ) -> Result:
        """Run one turn of *code* in the agent's persistent workspace."""
        with self._dict_lock:
            workspace = self._workspaces.setdefault(agent_id, {})
            lock = self._locks.setdefault(agent_id, threading.Lock())

        with lock:  # per-agent serialization: a second turn blocks
            if namespace:
                workspace.update(namespace)  # caller namespace wins
            snapshot = _snapshot_workspace(workspace)
            prev_result = workspace.pop("result", None)  # per-turn slot

            if timeout is None:
                return self._run_sync(agent_id, workspace, code, prev_result)
            return self._run_timed(
                agent_id, workspace, code, prev_result, timeout, snapshot
            )

    def install(self, agent_id: str, generator: Any) -> None:
        """Register *generator* as the agent's resumable ``__runner``.

        Replaces any previously installed runner. The generator is advanced
        one yield-window per :meth:`advance` call.
        """
        with self._dict_lock:
            self._workspaces.setdefault(agent_id, {})
            lock = self._locks.setdefault(agent_id, threading.Lock())
        with lock:
            self.clear_cancel(agent_id)
            self._runners[agent_id] = generator
            self._runner_states[agent_id] = "active"

    def advance(
        self, agent_id: str, timeout: float | None = None
    ) -> AdvanceOutcome:
        """Advance the installed runner one yield-window (one step).

        Runs under the per-agent lock. With a timeout, the step runs in a
        daemon worker thread joined for *timeout* seconds; on timeout the
        workspace is rolled back to the per-advance snapshot and the runner is
        abandoned (never resumed).
        """
        with self._dict_lock:
            workspace = self._workspaces.setdefault(agent_id, {})
            lock = self._locks.setdefault(agent_id, threading.Lock())

        with lock:
            runner = self._runners.get(agent_id)
            state = self._runner_states.get(agent_id)
            if runner is None:
                if state == "abandoned":
                    return AdvanceOutcome(kind="abandoned")
                return AdvanceOutcome(kind="not_installed")
            if state == "suspended":
                return AdvanceOutcome(kind="suspended")
            if timeout is None:
                return self._advance_sync(agent_id, workspace, runner)
            return self._advance_timed(agent_id, workspace, runner, timeout)

    def inject(self, agent_id: str, namespace: dict) -> None:
        """Merge *namespace* into the agent's workspace (caller values win).

        Used by the pump to refresh the in-code surface between steps.
        """
        with self._dict_lock:
            workspace = self._workspaces.setdefault(agent_id, {})
            lock = self._locks.setdefault(agent_id, threading.Lock())
        with lock:
            workspace.update(namespace)

    def bind_cancel(self, agent_id: str, predicate: Callable[[], bool]) -> None:
        """Attach an external cancel predicate to *agent_id*'s turns.

        The pump binds the runtime's stop flag here so a running turn can
        observe cancellation between blocks (instead of only after the step
        returns or times out). The predicate is polled from the turn's
        worker thread; it must be cheap and thread-safe.
        """
        with self._dict_lock:
            self._cancel_predicates[agent_id] = predicate

    def unbind_cancel(self, agent_id: str) -> None:
        """Drop *agent_id*'s external cancel predicate (pump teardown)."""
        with self._dict_lock:
            self._cancel_predicates.pop(agent_id, None)

    def request_cancel(self, agent_id: str) -> None:
        """Mark *agent_id*'s running turn cancelled (engine-owned flag)."""
        with self._dict_lock:
            self._cancel_events.setdefault(agent_id, threading.Event()).set()

    def clear_cancel(self, agent_id: str) -> None:
        """Forget a prior cancellation (a fresh runner install does this)."""
        with self._dict_lock:
            event = self._cancel_events.get(agent_id)
            if event is not None:
                event.clear()

    def cancelled(self, agent_id: str) -> bool:
        """True when *agent_id*'s running turn has been cancelled."""
        with self._dict_lock:
            event = self._cancel_events.get(agent_id)
            predicate = self._cancel_predicates.get(agent_id)
        if event is not None and event.is_set():
            return True
        return bool(predicate is not None and predicate())

    def suspend(self, agent_id: str) -> None:
        """Park the installed runner: advance will not run it until resumed."""
        with self._dict_lock:
            lock = self._locks.setdefault(agent_id, threading.Lock())
        with lock:
            if agent_id in self._runners:
                self._runner_states[agent_id] = "suspended"

    def resume(self, agent_id: str) -> None:
        """Continue a suspended runner from the same point."""
        with self._dict_lock:
            lock = self._locks.setdefault(agent_id, threading.Lock())
        with lock:
            if self._runner_states.get(agent_id) == "suspended":
                self._runner_states[agent_id] = "active"

    def kill(self, agent_id: str) -> None:
        """Abandon the installed runner and clear it; it is never resumed.

        Also raises the engine cancel flag so a blocking nested call still
        running in the abandoned runner's thread (e.g. ``bash``) is killed.
        """
        with self._dict_lock:
            lock = self._locks.setdefault(agent_id, threading.Lock())
        with lock:
            if agent_id in self._runners:
                self._abandon_runner(agent_id)
            self.request_cancel(agent_id)

    def run_block(self, agent_id: str, code: str) -> Result:
        """Execute *code* against the agent's workspace WITHOUT the lock.

        Reentrant nested exec: safe to call from inside an advance (the pump
        already holds the per-agent lock during a step). A runaway nested
        block is caught only by the outer step timeout; there is no nested
        timeout parameter (it would be unenforced).
        """
        with self._dict_lock:
            workspace = self._workspaces.get(agent_id)
        if workspace is None:
            return Result(done=True, ok=False, reason="no workspace for agent")
        # Cancellation boundary: a cancelled turn stops at the next block
        # instead of running to the end of the step.
        if self.cancelled(agent_id):
            raise TurnCancelled("turn cancelled")
        try:
            exec(code, workspace)
        except TurnCancelled:
            raise
        except BaseException as exc:  # noqa: BLE001 - contained per INFO-005
            return Result(
                done=True, ok=False, reason=f"{type(exc).__name__}: {exc}"
            )
        # A block may itself have observed the cancel signal (e.g. ``bash``
        # killed its subprocess and returned): stop before the next block.
        if self.cancelled(agent_id):
            raise TurnCancelled("turn cancelled")
        return self._result_from(workspace)

    def inject_nolock(self, agent_id: str, namespace: dict) -> None:
        """Merge *namespace* into the workspace WITHOUT the per-agent lock.

        Reentrant companion to :meth:`inject`: safe to call from inside an
        advance (the pump already holds the per-agent lock during a step),
        mirroring :meth:`run_block`'s reentrancy. Used by the fabrication
        kit's ``run_block``/``exec_block`` to refresh the in-code surface
        between nested execs.
        """
        with self._dict_lock:
            workspace = self._workspaces.get(agent_id)
        if workspace is not None:
            workspace.update(namespace)

    def reset(self, agent_id: str) -> None:
        """Drop the agent's workspace and lock; the next execute starts fresh.

        Not safe to call concurrently with an in-flight ``execute`` on the
        same agent.
        """
        with self._dict_lock:
            self._workspaces.pop(agent_id, None)
            self._locks.pop(agent_id, None)
            self._runners.pop(agent_id, None)
            self._runner_states.pop(agent_id, None)
            self._cancel_events.pop(agent_id, None)
            self._cancel_predicates.pop(agent_id, None)

    def globals_for(self, agent_id: str) -> dict:
        """Return a copy of the agent's workspace (inspection only)."""
        with self._dict_lock:
            workspace = self._workspaces.get(agent_id)
        return dict(workspace) if workspace is not None else {}

    def has_workspace(self, agent_id: str) -> bool:
        """True once the agent has a workspace (i.e. has run a turn)."""
        with self._dict_lock:
            return agent_id in self._workspaces

    # -- internals --------------------------------------------------------- #

    def _advance_sync(
        self, agent_id: str, workspace: dict, runner: Any
    ) -> AdvanceOutcome:
        _set_thread_cancel(lambda: self.cancelled(agent_id))
        try:
            value = next(runner)
        except StopIteration:
            self._finish_runner(agent_id)
            return AdvanceOutcome(kind="finished")
        except TurnCancelled:
            self._abandon_runner(agent_id)
            return AdvanceOutcome(kind="cancelled", reason="step cancelled")
        except BaseException as exc:  # noqa: BLE001 - contained
            self._finish_runner(agent_id)
            return AdvanceOutcome(
                kind="error", reason=f"{type(exc).__name__}: {exc}"
            )
        finally:
            _set_thread_cancel(None)
        return AdvanceOutcome(kind="yield", value=value)

    def _join_timed(
        self, agent_id: str, worker: threading.Thread, timeout: float
    ) -> str:
        """Join *worker* up to *timeout*, polling cancellation in slices.

        Returns ``"done"`` (worker ended), ``"cancelled"`` (cancel observed
        while it was still running) or ``"timeout"``.
        """
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return "timeout" if worker.is_alive() else "done"
            worker.join(min(_CANCEL_POLL, remaining))
            if not worker.is_alive():
                return "done"
            if self.cancelled(agent_id):
                return "cancelled"

    def _advance_timed(
        self,
        agent_id: str,
        workspace: dict,
        runner: Any,
        timeout: float,
    ) -> AdvanceOutcome:
        snapshot = _snapshot_workspace(workspace)
        outcome: dict = {}

        def run() -> None:
            _set_thread_cancel(lambda: self.cancelled(agent_id))
            try:
                value = next(runner)
                outcome["kind"] = "yield"
                outcome["value"] = value
            except StopIteration:
                outcome["kind"] = "finished"
            except TurnCancelled:
                outcome["kind"] = "cancelled"
            except BaseException as exc:  # noqa: BLE001 - contained
                outcome["kind"] = "error"
                outcome["reason"] = f"{type(exc).__name__}: {exc}"
            finally:
                _set_thread_cancel(None)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        state = self._join_timed(agent_id, worker, timeout)
        if state != "done":
            # Timed out or cancelled: the worker may still be mutating
            # *workspace*; discard it and roll back to the per-advance
            # snapshot (INFO-020, now per-step). The thread itself cannot be
            # killed; it is confined to the discarded dict.
            with self._dict_lock:
                self._workspaces[agent_id] = snapshot
            self._abandon_runner(agent_id)
            if state == "cancelled":
                return AdvanceOutcome(kind="cancelled", reason="step cancelled")
            return AdvanceOutcome(
                kind="timeout", reason=f"step timed out after {timeout}s"
            )
        kind = outcome.get("kind")
        if kind == "yield":
            return AdvanceOutcome(kind="yield", value=outcome.get("value"))
        if kind == "finished":
            self._finish_runner(agent_id)
            return AdvanceOutcome(kind="finished")
        if kind == "cancelled":
            self._abandon_runner(agent_id)
            return AdvanceOutcome(kind="cancelled", reason="step cancelled")
        self._finish_runner(agent_id)
        return AdvanceOutcome(kind="error", reason=outcome.get("reason", ""))

    def _finish_runner(self, agent_id: str) -> None:
        """Drop a runner that ended on its own (StopIteration or a raise)."""
        with self._dict_lock:
            self._runners.pop(agent_id, None)
            self._runner_states.pop(agent_id, None)

    def _abandon_runner(self, agent_id: str) -> None:
        """Drop a runner that must never be resumed (timeout or kill)."""
        with self._dict_lock:
            self._runners.pop(agent_id, None)
            self._runner_states[agent_id] = "abandoned"

    def _run_sync(
        self, agent_id: str, workspace: dict, code: str, prev_result: object
    ) -> Result:
        _set_thread_cancel(lambda: self.cancelled(agent_id))
        try:
            exec(code, workspace)
        except TurnCancelled:
            self._restore_result(workspace, prev_result)
            return Result(done=True, ok=False, reason="turn cancelled")
        except BaseException as exc:  # noqa: BLE001 - contained per INFO-005
            self._restore_result(workspace, prev_result)
            return Result(
                done=True, ok=False, reason=f"{type(exc).__name__}: {exc}"
            )
        finally:
            _set_thread_cancel(None)
        return self._result_from(workspace)

    def _run_timed(
        self,
        agent_id: str,
        workspace: dict,
        code: str,
        prev_result: object,
        timeout: float,
        snapshot: dict,
    ) -> Result:
        outcome: dict = {}

        def run() -> None:
            _set_thread_cancel(lambda: self.cancelled(agent_id))
            try:
                exec(code, workspace)
                outcome["ok"] = True
            except TurnCancelled:
                outcome["cancelled"] = True
            except BaseException as exc:  # noqa: BLE001 - contained
                outcome["ok"] = False
                outcome["error"] = exc
            finally:
                _set_thread_cancel(None)

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        state = self._join_timed(agent_id, worker, timeout)
        if state != "done":
            # Timed out or cancelled: the worker may still be mutating
            # *workspace*; discard it and roll back to the turn-start
            # snapshot (INFO-020). The thread itself cannot be killed; it is
            # confined to the discarded dict.
            with self._dict_lock:
                self._workspaces[agent_id] = snapshot
            if state == "cancelled":
                return Result(done=True, ok=False, reason="turn cancelled")
            return Result(done=True, ok=False, reason="turn timed out")
        if outcome.get("cancelled"):
            with self._dict_lock:
                self._workspaces[agent_id] = snapshot
            return Result(done=True, ok=False, reason="turn cancelled")
        if not outcome.get("ok", False):
            self._restore_result(workspace, prev_result)
            exc = outcome["error"]
            return Result(
                done=True, ok=False, reason=f"{type(exc).__name__}: {exc}"
            )
        return self._result_from(workspace)

    @staticmethod
    def _restore_result(workspace: dict, prev_result: object) -> None:
        if prev_result is not None:
            workspace["result"] = prev_result

    @staticmethod
    def _result_from(workspace: dict) -> Result:
        value = workspace.get("result")
        if isinstance(value, Result):
            return value
        return Result(done=True, ok=True, value=None)