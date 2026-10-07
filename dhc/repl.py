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
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from .models import Result


@dataclass(frozen=True)
class AdvanceOutcome:
    """Outcome of one :meth:`ReplEngine.advance` call.

    ``kind`` is one of:

    - ``"yield"`` — the runner yielded ``value`` and remains active.
    - ``"finished"`` — the runner raised StopIteration; it is done.
    - ``"timeout"`` — the step exceeded its timeout; the runner was abandoned
      and the workspace was rolled back to the per-advance snapshot.
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
    - ``run_block(agent_id, code, timeout=None) -> Result``
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
      background, but it only ever mutates the discarded pre-rollback dict, so
      the workspace stays usable and uncorrupted. The snapshot is shallow:
      in-place mutation of a nested object by a timed-out turn is not rolled
      back (deep-copying arbitrary workspace contents is neither safe nor
      cheap).

    Resumable-run primitives (IMP-001 Step 1)
    -----------------------------------------
    - **Runner**: :meth:`install` registers a resumable generator as the
      agent's ``__runner`` (engine-side; the workspace-citizen exposure lands
      with the fabrication kit in Step 2). :meth:`advance` runs one
      yield-window (one step) under the per-agent lock and returns an
      :class:`AdvanceOutcome` describing what the generator yielded.
    - **Per-advance snapshot**: each timed advance snapshots the workspace
      (the shallow-copy mechanism of INFO-020, now per-step). On timeout the
      workspace is rolled back to the snapshot and the generator is
      **abandoned** — never resumed, because the old worker thread may still
      be mutating the discarded snapshot dict. Sequential join-ordered
      advances are safe.
    - **Lifecycle**: :meth:`suspend` parks the runner (advance does not run
      it), :meth:`resume` continues it from the same point, :meth:`kill`
      abandons it and clears the installed runner. Cancellation lands between
      steps (INFO-040).
    - **Nested exec reentrancy**: :meth:`run_block` executes a code block
      against the workspace WITHOUT taking the per-agent lock (the pump
      already holds it during an advance), so a nested ``run_block`` from
      inside a generator step does not deadlock. A runaway nested block is
      caught only by the outer step timeout; ``run_block``'s own ``timeout``
      argument is accepted for API compatibility and is not enforced by the
      nested call.
    """

    def __init__(self) -> None:
        self._workspaces: dict[str, dict] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._runners: dict[str, Any] = {}
        self._runner_states: dict[str, str] = {}
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
            snapshot = dict(workspace)
            prev_result = workspace.pop("result", None)  # per-turn slot

            if timeout is None:
                return self._run_sync(workspace, code, prev_result)
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
        """Abandon the installed runner and clear it; it is never resumed."""
        with self._dict_lock:
            lock = self._locks.setdefault(agent_id, threading.Lock())
        with lock:
            if agent_id in self._runners:
                self._abandon_runner(agent_id)

    def run_block(
        self, agent_id: str, code: str, timeout: float | None = None
    ) -> Result:
        """Execute *code* against the agent's workspace WITHOUT the lock.

        Reentrant nested exec: safe to call from inside an advance (the pump
        already holds the per-agent lock during a step). A runaway nested
        block is caught only by the outer step timeout; *timeout* is accepted
        for API compatibility and is not enforced here.
        """
        with self._dict_lock:
            workspace = self._workspaces.get(agent_id)
        if workspace is None:
            return Result(done=True, ok=False, reason="no workspace for agent")
        try:
            exec(code, workspace)
        except BaseException as exc:  # noqa: BLE001 - contained per INFO-005
            return Result(
                done=True, ok=False, reason=f"{type(exc).__name__}: {exc}"
            )
        return self._result_from(workspace)

    def inject_nolock(self, agent_id: str, namespace: dict) -> None:
        """Merge *namespace* into the workspace WITHOUT the per-agent lock.

        Reentrant companion to :meth:`inject`: safe to call from inside an
        advance (the pump already holds the per-agent lock during a step),
        mirroring :meth:`run_block`'s reentrancy. Used by the fabrication
        kit's ``run_block`` to refresh the in-code surface between nested
        execs.
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
        try:
            value = next(runner)
        except StopIteration:
            self._finish_runner(agent_id)
            return AdvanceOutcome(kind="finished")
        except BaseException as exc:  # noqa: BLE001 - contained
            self._finish_runner(agent_id)
            return AdvanceOutcome(
                kind="error", reason=f"{type(exc).__name__}: {exc}"
            )
        return AdvanceOutcome(kind="yield", value=value)

    def _advance_timed(
        self,
        agent_id: str,
        workspace: dict,
        runner: Any,
        timeout: float,
    ) -> AdvanceOutcome:
        snapshot = dict(workspace)
        outcome: dict = {}

        def run() -> None:
            try:
                value = next(runner)
                outcome["kind"] = "yield"
                outcome["value"] = value
            except StopIteration:
                outcome["kind"] = "finished"
            except BaseException as exc:  # noqa: BLE001 - contained
                outcome["kind"] = "error"
                outcome["reason"] = f"{type(exc).__name__}: {exc}"

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            # Timed out: the worker may still be mutating *workspace*; discard
            # it and roll back to the per-advance snapshot (INFO-020, now
            # per-step).
            with self._dict_lock:
                self._workspaces[agent_id] = snapshot
            self._abandon_runner(agent_id)
            return AdvanceOutcome(kind="timeout")
        kind = outcome.get("kind")
        if kind == "yield":
            return AdvanceOutcome(kind="yield", value=outcome.get("value"))
        if kind == "finished":
            self._finish_runner(agent_id)
            return AdvanceOutcome(kind="finished")
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
        self, workspace: dict, code: str, prev_result: object
    ) -> Result:
        try:
            exec(code, workspace)
        except BaseException as exc:  # noqa: BLE001 - contained per INFO-005
            self._restore_result(workspace, prev_result)
            return Result(
                done=True, ok=False, reason=f"{type(exc).__name__}: {exc}"
            )
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
            try:
                exec(code, workspace)
                outcome["ok"] = True
            except BaseException as exc:  # noqa: BLE001 - contained
                outcome["ok"] = False
                outcome["error"] = exc

        worker = threading.Thread(target=run, daemon=True)
        worker.start()
        worker.join(timeout)
        if worker.is_alive():
            # Timed out: the worker may still be mutating *workspace*; discard
            # it and roll back to the turn-start snapshot (INFO-020).
            with self._dict_lock:
                self._workspaces[agent_id] = snapshot
            return Result(done=True, ok=False, reason="turn timed out")
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