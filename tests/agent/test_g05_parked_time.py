"""G-05 (decision 0008): parked-time semantics for the wall-clock ceiling.

INFO-053 puts waiting under agent control — "waiting on others consumes no
agent budget" — and ceiling caps under runtime control. Decision 0008
resolves the ambiguity: the wall-clock ceiling credits time spent parked on
``yield Await(child)`` / ``yield Sleep(t)``; it still binds for non-parked
wall time; runaway steps are still bounded by the step timeout; and
cancellation still terminates a parked agent (the containment for an agent
that parks forever).
"""

import threading
import time

import pytest

from dhc.data.models import AgentStatus, EventKind, is_terminal


# --------------------------------------------------------------------------- #
# Helpers (same shape as tests/agent/test_runtime.py)
# --------------------------------------------------------------------------- #


def wait_for(predicate, timeout: float = 10.0) -> bool:
    """Poll *predicate* until it is true or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _pumped_runtime(tmp_path, **settings_kwargs):
    """A fully-wired runtime (ReplEngine + fabrication kit) over tmp_path."""
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


class _BlockingDriver:
    """A driver that blocks forever on the first call (for cancellation)."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, agent):
        self.entered.set()
        self.release.wait(timeout=30)
        return None


# --------------------------------------------------------------------------- #
# G-05 acceptance: parked time is excluded from the wall-clock ceiling
# --------------------------------------------------------------------------- #


def test_g05_parked_await_excluded_from_wall_clock(tmp_path):
    """An agent parked on ``yield Await(slow_child)`` longer than
    ``timeout_seconds`` — with the child alive the whole time — does NOT
    trip the wall-clock ceiling: parked time is credited (0008)."""
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(timeout_seconds=1.0)),
    )
    try:
        # The child is slow by WAITING (yield Sleep), not by burning a
        # step: its own wall clock is credited too, so only the parent's
        # Await-park is the probe under test.
        slow_child = MockDriver(
            [
                "__runner = '''def __runner__(ctx):\n"
                "    yield Sleep(1.5)\n"
                "    complete('slow child done')\n"
                "'''\n"
            ]
        )
        parent = rt.spawn(
            "parent",
            driver=MockDriver(
                [
                    "__runner = '''def __runner__(ctx):\n"
                    "    c1 = spawn('slow child', driver=slow_child)\n"
                    "    ctx['state']['await_started'] = True\n"
                    "    yield Await(c1)\n"
                    "    complete('parent done')\n"
                    "'''\n"
                ]
            ),
            namespace={"slow_child": slow_child},
        )
        # The parent's runner parks on Await(c1) once the flag is set.
        assert wait_for(
            lambda: rt.repl_engine.globals_for(parent.id)
            .get("state", {})
            .get("await_started")
        )
        (child_id,) = rt.children_of(parent.id)
        # The child sleeps 1.5s against the parent's 1.0s ceiling: the
        # parent is parked longer than timeout_seconds with the child
        # alive. Under pre-0008 semantics the parent would be killed at
        # resume for the child's slowness.
        completion = parent.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "parent done"
        # The child completed too (the mesh stayed alive).
        assert rt.await_(child_id).status == AgentStatus.completed
        # No wall_clock crash event was ever emitted for the parent.
        assert not any(
            e.kind == EventKind.crash and e.payload.get("cap") == "wall_clock"
            for e in rt.events(parent.id)
        )
    finally:
        rt.stop()


def test_g05_busy_agent_still_trips_wall_clock(tmp_path):
    """The ceiling still binds for NON-parked wall time: an agent that
    keeps stepping (bare yields, never parked) trips wall_clock even
    though every individual step is fast."""
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(timeout_seconds=0.05)),
    )
    try:
        handle = rt.spawn(
            "busy",
            driver=MockDriver(
                [
                    "__runner = '''def __runner__(ctx):\n"
                    "    while True:\n"
                    "        yield\n"
                    "'''\n"
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.failed
        assert "cap exceeded" in completion.reason
        assert "wall_clock" in completion.reason
        # A crash event was emitted with the cap name and the limit.
        crash = [e for e in rt.events(handle.id) if e.kind == EventKind.crash]
        assert any(
            e.payload.get("cap") == "wall_clock"
            and e.payload.get("limit") == pytest.approx(0.05)
            for e in crash
        )
    finally:
        rt.stop()


def test_g05_runaway_step_still_trips_step_timeout(tmp_path):
    """Crediting parked time does not weaken runaway containment: a
    runaway ``while True: pass`` step is still bounded by the step timeout
    (rollback + timeout settlement), not by the wall clock."""
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(tmp_path, max_turn_seconds=0.2)
    try:
        runaway = rt.spawn(
            "runaway",
            driver=MockDriver(["x = 'partial'\nwhile True: pass"]),
        )
        t0 = time.monotonic()
        completion = runaway.await_()
        assert time.monotonic() - t0 < 5
        assert completion.status == AgentStatus.timeout
        assert any(e.kind == EventKind.timeout for e in rt.events(runaway.id))
        # The workspace was rolled back: no partial mutation from the step.
        assert "x" not in rt.repl_engine.globals_for(runaway.id)
    finally:
        rt.stop()


def test_g05_cancel_terminates_parked_agent(tmp_path):
    """Cancellation still terminates a PARKED agent — the containment for
    an agent that parks forever (the wall clock no longer kills it while
    parked)."""
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(tmp_path)
    blocking = _BlockingDriver()
    try:
        parent = rt.spawn(
            "parent",
            driver=MockDriver(
                [
                    "__runner = '''def __runner__(ctx):\n"
                    "    c1 = spawn('blocked child', driver=blocking_driver)\n"
                    "    ctx['state']['await_started'] = True\n"
                    "    yield Await(c1)\n"
                    "    complete('parent done')\n"
                    "'''\n"
                ]
            ),
            namespace={"blocking_driver": blocking},
        )
        assert wait_for(
            lambda: rt.repl_engine.globals_for(parent.id)
            .get("state", {})
            .get("await_started")
        )
        # The parent's runner is parked in the engine (suspended) while the
        # pump services the Await.
        assert wait_for(
            lambda: rt.repl_engine._runner_states.get(parent.id) == "suspended"
        )
        res = parent.cancel("stop now")
        assert res.done and not res.ok
        assert wait_for(lambda: rt.poll(parent.id) == AgentStatus.cancelled)
        # The runner was killed: advance returns abandoned (never resumed).
        assert rt.repl_engine.advance(parent.id).kind == "abandoned"
        # The child settles once released (not leaked), and the mesh stays
        # alive: a sibling spawned after still completes.
        (child_id,) = rt.children_of(parent.id)
        blocking.release.set()
        assert wait_for(lambda: is_terminal(rt.poll(child_id)))
        sibling = rt.spawn("sibling", driver=MockDriver.single("complete('fine')"))
        assert sibling.await_().status == AgentStatus.completed
    finally:
        blocking.release.set()
        rt.stop()


def test_g05_wall_clock_credit_arithmetic(tmp_path):
    """The credit arithmetic, pinned directly: 10s of elapsed wall time
    against a 5s ceiling trips; crediting 6s of parked time (10-6=4 < 5)
    does not; crediting only 4s (10-4=6 > 5) still trips."""
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(timeout_seconds=5.0)),
    )
    try:
        handle = rt.spawn("capcheck", driver=MockDriver.single("complete('ok')"))
        assert handle.await_().status == AgentStatus.completed
        # 10s of elapsed wall time, no credit: trips.
        cap = rt._caps_watchdog(handle.id, rt.engine, 0, time.monotonic() - 10.0)
        assert cap == "wall_clock"
        # 6s of that was parked: 10 - 6 = 4 < 5 -> no trip.
        cap = rt._caps_watchdog(
            handle.id, rt.engine, 0, time.monotonic() - 10.0, parked_seconds=6.0
        )
        assert cap is None
        # Only 4s credited: 10 - 4 = 6 > 5 -> still trips (no over-credit).
        cap = rt._caps_watchdog(
            handle.id, rt.engine, 0, time.monotonic() - 10.0, parked_seconds=4.0
        )
        assert cap == "wall_clock"
    finally:
        rt.stop()
