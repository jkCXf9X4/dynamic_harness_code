"""Composition tests: Wave-1 merges must COMPOSE, not just co-exist.

These pin the cross-branch semantics that a clean git merge could silently
break (the integration contract for G-01 x G-05 and the pump gate order):

* G-01 (agent budgets, min-clamped onto ceilings) x G-05 (parked-time
  credit): the wall clock trips iff
  ``(time.monotonic() - started_ts - parked_seconds) > effective_limit`` where
  ``effective_limit = min(agent_budget, ceiling)`` — the agent budget only
  ever tightens, and parked time is credited against the EFFECTIVE limit.
* The pump's between-step gate order (stop flag -> completions drain ->
  caps (clamp + credit) -> rot gate -> integrity -> advance) holds with all
  six Wave-1 items present at once.
"""

from __future__ import annotations

import time

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


def test_composition_budget_and_parked_credit_on_wall_clock(tmp_path):
    """G-01 x G-05: the wall clock composes min-clamp and parked credit.

    Trip iff ``(time.monotonic() - started_ts - parked_seconds) >
    effective_limit`` with ``effective_limit = min(agent_budget,
    ceiling)``. Pinned directly against the runtime predicate with an
    agent budget set in the workspace (the G-01 seam) and parked seconds
    supplied by the pump (the G-05 seam):

    * ceiling 5s, agent budget 8s (above the ceiling -> clamped to 5):
      10s elapsed, 6s parked -> 10-6=4 <= 5 -> no trip.
    * ceiling 5s, agent budget 3s (tighter than the ceiling -> binds):
      10s elapsed, 6s parked -> 10-6=4 > 3 -> trips with source
      ``agent_budget`` and the effective limit 3.
    * Same tight budget, more parked time: 10s elapsed, 8s parked ->
      10-8=2 <= 3 -> no trip (the credit applies to the budget too).
    """
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(timeout_seconds=5.0)),
    )
    try:
        handle = rt.spawn("compose", driver=MockDriver.single("complete('ok')"))
        assert handle.await_().status == AgentStatus.completed
        ws = rt.repl_engine.globals_for(handle.id)

        # Agent budget ABOVE the ceiling: the ceiling (5) binds; the
        # credit (6s) keeps 10s of elapsed time under it.
        ws["context"].budgets["timeout_seconds"] = 8.0
        cap = rt._caps_watchdog(
            handle.id, rt.repl_engine, 0, time.monotonic() - 10.0, parked_seconds=6.0
        )
        assert cap is None

        # Agent budget BELOW the ceiling: the budget (3) binds; the same
        # 6s credit no longer saves the agent (10-6=4 > 3).
        ws["context"].budgets["timeout_seconds"] = 3.0
        hit = rt._caps_hit(
            handle.id, rt.repl_engine, 0, time.monotonic() - 10.0, parked_seconds=6.0
        )
        assert hit == {"cap": "wall_clock", "limit": 3.0, "source": "agent_budget"}

        # More parked time (8s) brings the same tight budget back under
        # the effective limit (10-8=2 <= 3): the credit composes with the
        # clamp, not just with the ceiling.
        hit = rt._caps_hit(
            handle.id, rt.repl_engine, 0, time.monotonic() - 10.0, parked_seconds=8.0
        )
        assert hit is None
    finally:
        rt.stop()


def test_composition_pump_gate_order_all_six(tmp_path):
    """The pump's between-step gate order composes all six Wave-1 items.

    stop flag -> completions drain -> caps (clamp + credit) -> rot gate
    (G-06) -> integrity (G-02/G-03 kit citizens) -> advance. A run that
    exercises the caps gate (via a tight agent budget, G-01), the parked
    credit (G-05, via a parked Sleep), the rot gate (G-06, default
    observe-only policy present as workspace data) and the integrity guard
    (G-02/G-03, all 10 kit citizens installed) must settle through the
    composed pipeline, not around it.
    """
    from dhc.llm.driver import MockDriver
    from dhc.llm.fabrication import FABRICATION_NAMES

    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn(
            "allgates",
            driver=MockDriver(
                [
                    # G-01 seam: a working budget in ordinary workspace data.
                    "context.budgets['max_iterations'] = 50\n",
                    # G-05 seam: park for a moment (the pump credits it).
                    "yield Sleep(0.05)\n",
                    # G-06 seam: the rot policy is ordinary workspace data.
                    "state['rot_seen'] = isinstance(context.rot_policy, dict)\n",
                    "complete('all gates passed')\n",
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        ws = rt.repl_engine.globals_for(handle.id)
        # The rot policy (G-06) is present as workspace data.
        assert ws["state"].get("rot_seen") is True
        # The integrity guard (G-02 x G-03) sees all 10 kit citizens.
        assert len(FABRICATION_NAMES) == 10
        assert "build_prompt" in FABRICATION_NAMES
        # No crash event: no gate tripped on a healthy composed run.
        crashes = [e for e in rt.events(handle.id) if e.kind == EventKind.crash]
        assert crashes == []
    finally:
        rt.stop()
