"""Tests for the IMP-001 Step 2 fabrication kit (D4).

Covers:
* the default ``__runner`` installed in a fresh workspace replicates the
  default script behavior (publish + complete) when advanced through
  ``ReplEngine.advance``;
* ``decide(context)`` with a MockDriver brain returns scripted blocks in
  order then ``None`` (settle);
* ``ensure_fabrication`` re-seeds a broken/deleted ``__runner`` (e.g.
  ``__runner = 42``) and emits a ``fabrication_reseeded`` event;
* the fabrication kit is present in the namespace (run_block, context,
  decide, channels, caps view, checkpoint helpers);
* ``examples/value_demo.py`` passes unmodified on the default loop.
"""

import subprocess
import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc.framework.agent import Agent, AgentHandle  # noqa: E402
from dhc.llm.driver import MockDriver  # noqa: E402
from dhc.tooling.fabrication import (  # noqa: E402
    DEFAULT_RUNNER_SOURCE,
    FABRICATION_NAMES,
    FabricationContext,
    fabrication_kit,
    make_default_runner,
)
from dhc.data.models import EventKind  # noqa: E402
from dhc.wiring import build_runtime  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _register_agent(rt, agent_id="a1", requirement="r"):
    """Register an agent on the runtime WITHOUT starting a worker thread.

    The committed ``Runtime.spawn`` starts a worker thread that races with
    manual ``ReplEngine.advance`` driving (driver=None settles immediately).
    Step 2 tests drive the default ``__runner`` directly, so they register
    the agent by hand — the same bookkeeping spawn does, minus the thread.
    """
    agent = Agent(
        id=agent_id,
        requirement=requirement,
        runtime=rt,
    )
    rt._agents[agent_id] = agent
    rt._handles[agent_id] = AgentHandle(agent_id, rt)
    rt._stop_flags[agent_id] = threading.Event()
    return agent


def _wired(tmp_path):
    rt = build_runtime(mock=True, artifact_root=str(tmp_path))
    rt.start()
    return rt


# --------------------------------------------------------------------------- #
# Default __runner replicates the default script behavior
# --------------------------------------------------------------------------- #


def test_default_runner_publish_and_complete(tmp_path):
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        engine.install(agent.id, make_default_runner(engine, agent.id, kit))

        # Turn 1: decide -> publish + complete block; run_block; observe.
        o1 = engine.advance(agent.id)
        assert o1.kind == "yield"
        assert o1.value == "step"
        assert agent._last_result is not None
        assert agent._last_result.ok is True
        assert agent._last_result.value == "done"
        assert rt.artifact_store_real.list_ids(), "publish must persist an artifact"

        # Turn 2: decide returns None -> settle; runner finishes.
        o2 = engine.advance(agent.id)
        assert o2.kind == "finished"
        assert rt.status(agent.id) == "completed"
        assert rt.result(agent.id).ok is True
    finally:
        rt.stop()


def test_default_runner_source_is_workspace_code(tmp_path):
    """The default __runner is authored as workspace code (a string)."""
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        assert kit["__runner"] == DEFAULT_RUNNER_SOURCE
        assert isinstance(DEFAULT_RUNNER_SOURCE, str)
        # The source defines a generator function named __runner__.
        assert "def __runner__" in DEFAULT_RUNNER_SOURCE
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# decide(context) with a MockDriver brain
# --------------------------------------------------------------------------- #


def test_decide_returns_scripted_blocks_then_none(tmp_path):
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        decide = kit["decide"]
        ctx = kit["context"]

        # The default kit's decide wraps a MockDriver with the default script
        # (one block), so the first call returns code, the second None.
        first = decide(ctx)
        assert isinstance(first, str)
        assert "publish" in first
        second = decide(ctx)
        assert second is None
    finally:
        rt.stop()


def test_decide_with_scripted_mockdriver_in_order(tmp_path):
    """decide(context) with a scripted MockDriver brain returns blocks in
    order then None — the MockDriver determinism contract."""
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        # Replace the kit's decide brain with a scripted MockDriver.
        script = ["x = 1", "x = 2", "x = 3"]
        kit["state"]["_driver"] = MockDriver(script)
        decide = kit["decide"]
        ctx = kit["context"]
        assert decide(ctx) == "x = 1"
        assert decide(ctx) == "x = 2"
        assert decide(ctx) == "x = 3"
        assert decide(ctx) is None
        # Bookkeeping moved into workspace state.
        assert kit["state"]["_calls"] == 4
    finally:
        rt.stop()


def test_decide_bookkeeping_in_workspace_state(tmp_path):
    """The driver's _turns/_calls bookkeeping lives in workspace state."""
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        # A real turn injects the kit into the workspace; do the same so a
        # namespace refresh finds the existing context/state.
        engine.inject(agent.id, kit)
        ctx = kit["context"]
        assert "_turns" not in kit["state"]
        kit["decide"](ctx)
        assert kit["state"]["_turns"] == 1
        assert kit["state"]["_calls"] == 1
        # A namespace refresh reuses the same state (no reset).
        kit2 = fabrication_kit(rt, engine, agent)
        assert kit2["state"] is kit["state"]
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# ensure_fabrication re-seeds broken/deleted fabrications
# --------------------------------------------------------------------------- #


def test_ensure_fabrication_reseeds_broken_runner(tmp_path):
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        # The agent broke its runner: __runner = 42.
        engine.inject(agent.id, {"__runner": 42})
        assert engine.globals_for(agent.id)["__runner"] == 42

        reseeded = kit["ensure_fabrication"]()
        assert "__runner" in reseeded
        # Re-seeded to the default source string.
        assert engine.globals_for(agent.id)["__runner"] == DEFAULT_RUNNER_SOURCE
        # An event was emitted (check before advancing: the runner's observe
        # step consumes the event stream). The re-seed is reported as a crash
        # event carrying the re-seeded names (no new EventKind member — the
        # committed test_models asserts the exact member set).
        events = rt.events(agent.id)
        kinds = [e.kind for e in events]
        assert EventKind.crash in kinds
        reseed_events = [
            e for e in events
            if e.kind == EventKind.crash and "fabrication_reseeded" in e.payload
        ]
        assert reseed_events and reseed_events[0].payload["fabrication_reseeded"] == reseeded
        # The engine-side runner is re-installed and drivable.
        o = engine.advance(agent.id)
        assert o.kind in ("yield", "finished")
    finally:
        rt.stop()


def test_ensure_fabrication_reseeds_deleted_runner(tmp_path):
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        # The agent deleted its runner entirely.
        engine.inject(agent.id, {"__runner": None})
        reseeded = kit["ensure_fabrication"]()
        assert "__runner" in reseeded
        assert engine.globals_for(agent.id)["__runner"] == DEFAULT_RUNNER_SOURCE
    finally:
        rt.stop()


def test_ensure_fabrication_noop_when_intact(tmp_path):
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        reseeded = kit["ensure_fabrication"]()
        assert reseeded == []
        kinds = [e.kind for e in rt.events(agent.id)]
        assert EventKind.crash not in kinds
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# G-03: every FABRICATION_NAMES citizen is guarded (re-seed + crash event)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("name", list(FABRICATION_NAMES))
def test_ensure_fabrication_reseeds_each_broken_citizen(tmp_path, name):
    """Breaking (or deleting) each of the 9 kit citizens in the workspace
    triggers a re-seed from the kit's canonical copy AND a
    ``fabrication_reseeded`` crash event naming that citizen.

    Covers the 5 previously-unguarded citizens (``ensure_fabrication``,
    ``checkpoint``, ``rollback``, ``compact``, ``caps``) as well as the 4
    already-guarded ones, so the guard is proven complete over
    :data:`FABRICATION_NAMES`.
    """
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        # Seed the workspace with the kit so it has a real, intact baseline.
        engine.inject(agent.id, kit)

        # Break the target citizen: a non-canonical, non-callable value for
        # the callable citizens; a non-string for the ``__runner`` source
        # (a custom runner *source string* is valid agent-authored loop code,
        # so only a non-string breaks the runner).
        broken = 42
        engine.inject(agent.id, {name: broken})
        assert engine.globals_for(agent.id)[name] == broken

        reseeded = kit["ensure_fabrication"]()
        assert reseeded == [name], f"expected only {name!r} re-seeded, got {reseeded!r}"

        # The citizen is restored to the kit's canonical copy.
        ws = engine.globals_for(agent.id)
        if name == "__runner":
            assert ws[name] == DEFAULT_RUNNER_SOURCE
        elif name == "context":
            assert isinstance(ws[name], FabricationContext)
        else:
            assert callable(ws[name])

        # A fabrication_reseeded crash event names the citizen.
        reseed_events = [
            e for e in rt.events(agent.id)
            if e.kind == EventKind.crash and "fabrication_reseeded" in e.payload
        ]
        assert reseed_events, f"no fabrication_reseeded event for {name!r}"
        assert reseed_events[0].payload["fabrication_reseeded"] == [name]
    finally:
        rt.stop()


def test_ensure_fabrication_reseeds_deleted_citizens(tmp_path):
    """Deleting (setting to None) each of the 9 citizens also triggers a
    re-seed + crash event — the guard covers both breakage and deletion."""
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        engine.inject(agent.id, kit)
        for name in FABRICATION_NAMES:
            engine.inject(agent.id, {name: None})
        reseeded = kit["ensure_fabrication"]()
        assert sorted(reseeded) == sorted(FABRICATION_NAMES)
        reseed_events = [
            e for e in rt.events(agent.id)
            if e.kind == EventKind.crash and "fabrication_reseeded" in e.payload
        ]
        assert reseed_events
        assert sorted(reseed_events[0].payload["fabrication_reseeded"]) == sorted(FABRICATION_NAMES)
    finally:
        rt.stop()


def test_ensure_fabrication_self_guard_no_recursion(tmp_path):
    """The self-guard case: a broken workspace ``ensure_fabrication`` is
    re-seedable. The pump invokes the kit-owned closure (via
    ``integrity.ensure_fabrication``), never the workspace copy, so re-seeding
    the workspace ``ensure_fabrication`` needs no recursion and no dependence
    on the broken copy.
    """
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        engine.inject(agent.id, kit)
        # Break the workspace copy of ensure_fabrication.
        engine.inject(agent.id, {"ensure_fabrication": 42})
        assert engine.globals_for(agent.id)["ensure_fabrication"] == 42

        # Drive the guard the way the pump does: through the kit-owned
        # closure, NOT the (broken) workspace copy.
        from dhc.framework import integrity
        integrity.ensure_fabrication(kit)

        # The workspace copy is re-seeded to a callable (the kit's closure).
        ws_ef = engine.globals_for(agent.id)["ensure_fabrication"]
        assert callable(ws_ef)
        # A crash event named the citizen.
        reseed_events = [
            e for e in rt.events(agent.id)
            if e.kind == EventKind.crash and "fabrication_reseeded" in e.payload
        ]
        assert reseed_events
        assert "ensure_fabrication" in reseed_events[0].payload["fabrication_reseeded"]
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# The fabrication kit is present in the namespace
# --------------------------------------------------------------------------- #


def test_kit_present_in_namespace(tmp_path):
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        ns = rt._build_namespace(agent)
        for name in FABRICATION_NAMES:
            assert name in ns, f"fabrication {name!r} not in namespace"
        assert callable(ns["decide"])
        assert callable(ns["run_block"])
        assert callable(ns["ensure_fabrication"])
        assert callable(ns["checkpoint"])
        assert callable(ns["rollback"])
        assert callable(ns["compact"])
        assert callable(ns["caps"])
        assert isinstance(ns["context"], FabricationContext)
        assert isinstance(ns["__runner"], str)
    finally:
        rt.stop()


def test_context_carries_guardrails_inbox_outbox_budgets_digests(tmp_path):
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        ctx = kit["context"]
        assert ctx.agent_id == agent.id
        assert ctx.guardrails == {}
        assert ctx.inbox == []
        assert ctx.outbox == []
        assert ctx.budgets == {}
        assert ctx.digests == {}
        d = ctx.as_dict()
        assert d["agent_id"] == agent.id
        assert d["agent"] is agent
    finally:
        rt.stop()


def test_caps_view_visible(tmp_path):
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        caps = kit["caps"]()
        assert "wall_clock_seconds" in caps
        assert "max_iterations" in caps
        assert "max_agents" in caps
        assert "max_depth" in caps
        assert "max_turn_seconds" in caps
    finally:
        rt.stop()


def test_checkpoint_rollback_compact_helpers(tmp_path):
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        engine.inject(agent.id, {"x": 1})
        idx = kit["checkpoint"]("milestone", done=("step1",))
        assert idx == 0
        engine.inject(agent.id, {"x": 99})
        assert engine.globals_for(agent.id)["x"] == 99
        assert kit["rollback"](idx) is True
        assert engine.globals_for(agent.id)["x"] == 1
        removed = kit["compact"]()
        assert removed == ["result"] or removed == []
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# examples/value_demo.py passes unmodified on the default loop
# --------------------------------------------------------------------------- #


def test_value_demo_runs_unmodified():
    """examples/value_demo.py must pass unmodified (exit 0) on the default
    loop — the backward-compat gate D4."""
    demo = REPO_ROOT / "examples" / "value_demo.py"
    assert demo.exists()
    proc = subprocess.run(
        [sys.executable, str(demo)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"value_demo.py failed (exit {proc.returncode})\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )
    assert "value report written" in proc.stdout