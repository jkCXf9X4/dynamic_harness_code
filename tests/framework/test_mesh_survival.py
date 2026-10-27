"""Mesh-survival guarantees.

A turn that overruns its step timeout settles ``failed`` (reason preserved,
timeout event emitted); cancellation reaches a running turn at the next
boundary and settles it ``cancelled`` with no further steps; and blocking
external calls (``bash``) run in their own process group and are SIGKILLed
on timeout or cancel, so no orphan survives.
"""

import os
import threading
import time

import pytest

from dhc.data.models import AgentStatus, EventKind
from dhc.framework.agent import bash

pytestmark = pytest.mark.slow


def _pumped_runtime(tmp_path, **settings_kwargs):
    from dhc.data.config import Settings
    from dhc.wiring import build_runtime

    settings = Settings(
        workspace_root=tmp_path,
        artifact_root=tmp_path,
        **settings_kwargs,
    )
    rt = build_runtime(mock=True, artifact_root=tmp_path, settings=settings)
    rt.start()
    return rt


def _wait_for(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _read_pid(path):
    assert _wait_for(lambda: path.exists() and path.read_text().strip())
    return int(path.read_text().strip())


def _is_dead(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    return False


def _set_flag_when_pid_ready(path, flag):
    def wait():
        for _ in range(300):
            if path.exists() and path.read_text().strip():
                flag.set()
                return
            time.sleep(0.01)

    threading.Thread(target=wait, daemon=True).start()


# -- timeout settles failed ------------------------------------------------ #


def test_step_timeout_settles_failed_with_reason(tmp_path):
    """A runaway step settles ``failed`` (not ``timeout``); the timeout
    reason survives on the completion and a timeout event is emitted."""
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(tmp_path, max_turn_seconds=0.2)
    try:
        runaway = rt.spawn(
            "runaway",
            driver=MockDriver(["x = 'partial'\nimport time\ntime.sleep(30)"]),
        )
        t0 = time.monotonic()
        completion = runaway.await_()
        assert time.monotonic() - t0 < 5
        assert completion.status == AgentStatus.failed
        assert "timed out" in completion.reason
        assert any(e.kind == EventKind.timeout for e in rt.events(runaway.id))
        # Workspace rollback still holds.
        assert "x" not in rt.repl_engine.globals_for(runaway.id)
        # The mesh stays alive.
        sibling = rt.spawn("sibling", driver=MockDriver(["complete('fine')"]))
        assert sibling.await_().status == AgentStatus.completed
    finally:
        rt.stop()


# -- cancellation reaches a running turn ----------------------------------- #


def test_cancel_mid_step_settles_cancelled_and_stops_steps(tmp_path):
    """Cancelling a turn blocked in ``bash`` settles it cancelled promptly
    and issues no further steps."""
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn("blocked", driver=MockDriver(["bash('sleep 30')"]))
        assert _wait_for(
            lambda: any(
                e.kind == EventKind.turn_started for e in rt.events(handle.id)
            )
        )
        time.sleep(0.2)  # let the step reach the blocking call
        t0 = time.monotonic()
        rt.cancel(handle.id)
        completion = handle.await_()
        assert time.monotonic() - t0 < 5, "cancel did not reach the running turn"
        assert completion.status == AgentStatus.cancelled
        steps_at_settle = sum(
            1 for e in rt.events(handle.id) if e.kind == EventKind.turn_started
        )
        time.sleep(0.3)
        steps_after = sum(
            1 for e in rt.events(handle.id) if e.kind == EventKind.turn_started
        )
        assert steps_after == steps_at_settle, "cancelled agent issued another step"
    finally:
        rt.stop()


# -- blocking external calls are killable ---------------------------------- #


def test_bash_timeout_kills_process_group(tmp_path):
    """On timeout the whole process group is SIGKILLed: no orphan survives."""
    pidfile = tmp_path / "child.pid"
    start = time.monotonic()
    out = bash(f"sleep 30 & echo $! > {pidfile}; wait", timeout=0.3)
    elapsed = time.monotonic() - start
    assert "timed out" in out
    assert elapsed < 3, f"bash blocked for {elapsed:.2f}s"
    pid = _read_pid(pidfile)
    assert _wait_for(lambda: _is_dead(pid)), "child process survived the timeout"


def test_bash_cancel_kills_process_group(tmp_path):
    """A cancel request kills the blocking call's group at the next poll."""
    from dhc.framework.repl import ReplEngine

    engine = ReplEngine()
    engine.inject("a1", {"bash": bash})
    flag = threading.Event()
    engine.bind_cancel("a1", flag.is_set)
    pidfile = tmp_path / "child.pid"

    def runner():
        engine.run_block(
            "a1",
            f"bash('sleep 30 & echo $! > {pidfile}; wait', timeout=60)",
        )
        yield "after"

    engine.install("a1", runner())
    _set_flag_when_pid_ready(pidfile, flag)
    start = time.monotonic()
    outcome = engine.advance("a1", timeout=20)
    elapsed = time.monotonic() - start
    assert outcome.kind == "cancelled"
    assert elapsed < 3, f"advance blocked for {elapsed:.2f}s"
    pid = _read_pid(pidfile)
    assert _wait_for(lambda: _is_dead(pid)), "child process survived the cancel"
