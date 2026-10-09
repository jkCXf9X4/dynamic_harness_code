"""H-04 (decision 0010): one monotonic time base for the wall-clock ceiling.

Decision 0008 recorded the interaction: the parked credit (monotonic) and
``started_ts`` (wall) must move to the same base TOGETHER — otherwise the
subtraction mixes clocks. Decision 0010 discharges it: the ceiling's origin
(``loop.py``) and comparison (``caps.py``) are both monotonic now, so a
wall-clock jump (NTP correction, VM resume, manual set) can neither trip nor
mask the cap.

These tests simulate the jump by monkeypatching ``time.time`` — the wall
clock the ceiling no longer reads. If the base were still mixed, the jump
would corrupt the comparison in the tested direction.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from dhc.data.models import AgentStatus, EventKind


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


def wait_for(predicate, timeout: float = 10.0) -> bool:
    """Poll *predicate* until it is true or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def _busy_runner_source() -> str:
    """A runner that stays busy (never parked) but yields often.

    A tiny ``time.sleep`` INSIDE the step keeps the agent genuinely busy
    (it is agent-code time, not parked time — parking is only the pump's
    ``yield Await``/``yield Sleep`` servicing) while letting the pump's
    between-step gates run often enough that the wall clock is reached
    before the 400-step iterations default. A pure ``while True: yield``
    tight loop would race the iterations cap instead.
    """
    return (
        "__runner = '''import time as _t\\n"
        "def __runner__(ctx):\\n"
        "    while True:\\n"
        "        _t.sleep(0.002)\\n"
        "        yield\\n"
        "'''\n"
    )


def _jump_wall_clock(monkeypatch, delta: float) -> None:
    """Make ``time.time`` jump by *delta* from its real value, forever.

    The ceiling no longer reads ``time.time`` (decision 0010), so the jump
    is only observable to code that still uses the wall clock — which is
    exactly what these tests assert the ceiling does not.
    """
    real_time = time.time

    def jumped_time():
        return real_time() + delta

    monkeypatch.setattr(time, "time", jumped_time)


# --------------------------------------------------------------------------- #
# H-04 acceptance: a wall-clock jump neither trips nor masks a cap
# --------------------------------------------------------------------------- #


def test_h04_wall_clock_jump_forward_does_not_trip(tmp_path, monkeypatch):
    """A FORWARD wall-clock jump (+3600 s) must not kill a healthy agent.

    Under the pre-0010 mixed base the jump would explode the elapsed term
    (``time.time() - started_ts``) and a busy agent with hours of budget
    left would be killed instantly. On the monotonic base the jump is
    invisible: the agent runs out its real budget only.
    """
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(timeout_seconds=5.0)),
    )
    try:
        # Jump the wall clock forward by an hour BEFORE spawning: every
        # wall-clock read the pump could make is an hour ahead.
        _jump_wall_clock(monkeypatch, 3600.0)
        handle = rt.spawn("healthy", driver=MockDriver.single("complete('ok')"))
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "ok"
        # No wall_clock crash event was ever emitted.
        assert not any(
            e.kind == EventKind.crash and e.payload.get("cap") == "wall_clock"
            for e in rt.events(handle.id)
        )
    finally:
        rt.stop()


def test_h04_wall_clock_jump_backward_does_not_mask(tmp_path, monkeypatch):
    """A BACKWARD wall-clock jump (-3600 s) must not mask a real cap trip.

    Under the pre-0010 mixed base the jump would make the elapsed term
    hugely negative, so a genuinely over-budget agent would stop tripping
    ``wall_clock`` for the rest of its run. On the monotonic base the busy
    agent is still killed by the ceiling.
    """
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(timeout_seconds=0.2)),
    )
    try:
        # Jump the wall clock BACK by an hour: any wall-clock-based
        # elapsed term would be ~-3600 s and never trip.
        _jump_wall_clock(monkeypatch, -3600.0)
        handle = rt.spawn(
            "overbudget", driver=MockDriver([_busy_runner_source()])
        )
        completion = handle.await_()
        # The ceiling still binds: the busy agent is killed by wall_clock.
        assert completion.status == AgentStatus.failed
        assert "cap exceeded" in completion.reason
        assert "wall_clock" in completion.reason
        crash = [e for e in rt.events(handle.id) if e.kind == EventKind.crash]
        assert any(
            e.payload.get("cap") == "wall_clock"
            and e.payload.get("limit") == pytest.approx(0.2)
            for e in crash
        )
    finally:
        rt.stop()


def test_h04_parked_credit_and_started_ts_same_base(tmp_path, monkeypatch):
    """0008's recorded interaction, pinned at the predicate seam.

    With ``started_ts`` taken from ``time.monotonic()`` (the pump's base),
    a wall-clock jump of either sign changes NOTHING about the trip
    decision: the credit and the origin are on the same clock, and the
    wall clock is not an input to the comparison at all.
    """
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(timeout_seconds=5.0)),
    )
    try:
        handle = rt.spawn("capcheck", driver=MockDriver.single("complete('ok')"))
        assert handle.await_().status == AgentStatus.completed

        # The trip decision with a monotonic origin, no jump: 10 s of
        # elapsed time against a 5 s ceiling trips (the 0008 arithmetic).
        started = time.monotonic() - 10.0
        assert rt._caps_watchdog(handle.id, rt.engine, 0, started) == "wall_clock"
        # 6 s of that was parked: 10 - 6 = 4 < 5 -> no trip.
        assert (
            rt._caps_watchdog(
                handle.id, rt.engine, 0, started, parked_seconds=6.0
            )
            is None
        )

        # Now jump the wall clock BOTH ways: the decision is unchanged in
        # both directions, because the comparison never reads the wall
        # clock. (Under the mixed base, +3600 s would trip the second
        # check and -3600 s would mask the first.)
        for delta in (3600.0, -3600.0):
            _jump_wall_clock(monkeypatch, delta)
            assert (
                rt._caps_watchdog(handle.id, rt.engine, 0, started)
                == "wall_clock"
            )
            assert (
                rt._caps_watchdog(
                    handle.id, rt.engine, 0, started, parked_seconds=6.0
                )
                is None
            )
    finally:
        rt.stop()


def test_h04_no_wall_clock_in_duration_math():
    """Grep-able invariant: the ceiling chain reads no wall clock.

    The two modules that own the wall-clock ceiling's duration math
    (``dhc.framework.caps`` — the comparison; ``dhc.framework.pump`` — the origin
    and the parked-credit measurement) must contain no ``time.time()``
    call: after decision 0010 the only legitimate clock in duration math
    is ``time.monotonic()``. Informational records (``created_ts``,
    ``settled_ts``, event timestamps) live in other modules and stay
    wall-clock by design.
    """
    import dhc.framework.caps as caps_mod
    import dhc.framework.pump as loop_mod

    for mod in (caps_mod, loop_mod):
        source = Path(mod.__file__).read_text(encoding="utf-8")
        assert "time.time()" not in source, (
            f"{mod.__name__} reads the wall clock in duration math — "
            "decision 0010 requires the monotonic base (time.monotonic())"
        )
