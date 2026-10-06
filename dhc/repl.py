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
"""

from __future__ import annotations

import threading

from .models import Result


class ReplEngine:
    """Per-agent persistent REPL.

    Public API
    ----------
    - ``execute(agent_id, code, namespace=None, timeout=None) -> Result``
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
    """

    def __init__(self) -> None:
        self._workspaces: dict[str, dict] = {}
        self._locks: dict[str, threading.Lock] = {}
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

    def reset(self, agent_id: str) -> None:
        """Drop the agent's workspace and lock; the next execute starts fresh.

        Not safe to call concurrently with an in-flight ``execute`` on the
        same agent.
        """
        with self._dict_lock:
            self._workspaces.pop(agent_id, None)
            self._locks.pop(agent_id, None)

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