"""IMP-001 Step 6 acceptance fixture: D1–D5 end to end.

One test per decision, each a small parent/child flow on the fully-wired
pumped runtime (ReplEngine + fabrication kit), plus the runaway-containment
scenario from the IMP containment table:

* D1  — resumable generator / trampoline: the agent replaces its ``__runner``
        with a custom generator; the pump compiles it (custom-runner seam) and
        drives it one yield-window at a time.
* D2  — full transparency + four hard gates: settlement at-most-once, crash
        containment, outer ceiling caps, cancellation grace.
* D3  — ``yield Await`` without step-budget burn; ``await_`` back-compat on
        the default loop.
* D4  — deterministic default fabrications: plain spawn on the default loop;
        ``ensure_fabrication`` re-seeds a broken fabrication and the agent
        continues. (``examples/value_demo.py`` passing unmodified is covered
        by ``tests/test_fabrication.py::test_value_demo_runs_unmodified`` and
        verified separately by the verifier.)
* D5  — guardrail placement: normative context-in at delegation, operational
        tripwire pump-evaluated between steps, reactions shipped as
        completion-style events on the parent's stream.
* Runaway containment — ``while True: pass`` bounded by the step timeout:
        timeout -> rollback -> settle, mesh alive.

Every containment scenario asserts sibling liveness (the mesh stays alive).
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc.driver import MockDriver  # noqa: E402
from dhc.errors import ChannelError  # noqa: E402
from dhc.fabrication import DEFAULT_RUNNER_SOURCE  # noqa: E402
from dhc.models import AgentStatus, Completion, EventKind  # noqa: E402


# --------------------------------------------------------------------------- #
# Helpers (replicated from tests/test_runtime.py so the fixture is
# self-contained — no cross-test-module imports)
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
    from dhc.config import Settings
    from dhc.wiring import build_runtime

    settings = Settings(
        workspace_root=tmp_path,
        artifact_root=tmp_path,
        **settings_kwargs,
    )
    rt = build_runtime(mock=True, artifact_root=tmp_path, settings=settings)
    rt.start()
    return rt


# --------------------------------------------------------------------------- #
# D1 — resumable generator / trampoline
# --------------------------------------------------------------------------- #


def test_d1_custom_runner_trampoline(tmp_path):
    """D1: the agent replaces its ``__runner`` with a custom generator (the
    workspace source string); the pump's custom-runner seam compiles it and
    drives it one yield-window at a time. The custom steps execute in order,
    each yield is classified by the pump, and the agent completes through the
    pump (not the legacy path)."""
    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn(
            "d1",
            driver=MockDriver(
                [
                    "__runner = '''\n"
                    "def __runner__(ctx):\n"
                    "    ctx['state']['steps'] = []\n"
                    "    ctx['state']['steps'].append('one')\n"
                    "    yield 'step-one'\n"
                    "    ctx['state']['steps'].append('two')\n"
                    "    yield 'step-two'\n"
                    "    ctx['state']['steps'].append('three')\n"
                    "    complete('custom runner done')\n"
                    "'''\n"
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "custom runner done"
        ws = rt.repl_engine.globals_for(handle.id)
        # The custom runner's steps executed in order.
        assert ws["state"]["steps"] == ["one", "two", "three"]
        # The pump drove the runner one yield-window at a time: step 1 is the
        # default runner executing the replacement block; steps 2–4 are the
        # custom runner's own steps (turn_started events; the default
        # runner's observe() drained step 1 into the state digest, the rest
        # are still on the bus because the custom runner never observes).
        digest = ws["state"]["digests"]["events"]
        bus_events = rt.events(handle.id)
        turn_steps = [
            e.payload.get("step")
            for e in digest + bus_events
            if e.kind == EventKind.turn_started
        ]
        assert turn_steps == [1, 2, 3, 4]
        # Each custom yield was classified by the pump: a turn_completed
        # event carries the step number of the yield that produced it.
        completed = [e for e in bus_events if e.kind == EventKind.turn_completed]
        assert [e.payload.get("step") for e in completed] == [1, 2, 3]
        # The agent completed through the pump (the wired runtime is pumped).
        assert rt.result(handle.id).ok
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# D2 — full transparency + four hard gates
# --------------------------------------------------------------------------- #


def test_d2a_settlement_at_most_once(tmp_path):
    """D2a: settlement is at-most-once through the pump — exactly one
    completion in the parent stream; a second settle raises ChannelError."""
    rt = _pumped_runtime(tmp_path)
    try:
        parent = rt.spawn(
            "parent",
            driver=MockDriver(
                [
                    "c1 = spawn('child', driver=MockDriver.single(\"complete('child done')\"))\n"
                    "complete('spawned')\n"
                ]
            ),
        )
        parent.await_()
        child_id = rt.children_of(parent.id)[0]
        rt.await_(child_id)
        completions = rt.completions(parent.id)
        assert len(completions) == 1
        assert completions[0].agent_id == child_id
        assert completions[0].status == AgentStatus.completed
        with pytest.raises(ChannelError):
            rt.completion_log().settle(
                Completion(agent_id=child_id, status=AgentStatus.failed, reason="late")
            )
    finally:
        rt.stop()


def test_d2b_crash_containment_broken_loop(tmp_path):
    """D2b: a broken loop costs one agent, not the mesh. The crasher replaces
    its ``__runner`` with a generator that raises mid-run; it settles failed
    while a healthy sibling completes and the parent stays alive."""
    rt = _pumped_runtime(tmp_path)
    try:
        parent = rt.spawn(
            "parent",
            driver=MockDriver(
                [
                    "c1 = spawn('crasher', driver=MockDriver.single(\"__runner = '''def __runner__(ctx):\\n    yield 'x'\\n    raise RuntimeError('broken loop')\\n'''\"))\n"
                    "c2 = spawn('healthy', driver=MockDriver.single(\"complete('healthy done')\"))\n"
                    "complete('spawned')\n"
                ]
            ),
        )
        parent.await_()
        child_ids = rt.children_of(parent.id)
        assert len(child_ids) == 2
        by_status = {rt.await_(cid).status for cid in child_ids}
        assert AgentStatus.failed in by_status
        assert AgentStatus.completed in by_status
        for cid in child_ids:
            completion = rt.await_(cid)
            if completion.status == AgentStatus.failed:
                assert "broken loop" in completion.reason
        # The mesh stayed alive: the parent completed after both children.
        assert rt.poll(parent.id) == AgentStatus.completed
    finally:
        rt.stop()


def test_d2c_outer_ceiling_cap(tmp_path):
    """D2c: an outer ceiling cap (max_iterations=1) force-stops the agent
    with 'cap exceeded' before it can finish; the mesh stays alive (a sibling
    spawned after still completes)."""
    from dhc.config import HarnessConfig, SafetyConfig

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(max_iterations=1)),
    )
    try:
        handle = rt.spawn("big", driver=MockDriver(["complete('done')"]))
        completion = handle.await_()
        assert completion.status == AgentStatus.failed
        assert "cap exceeded" in completion.reason
        assert "iterations" in completion.reason
        # A crash event was emitted with the cap name and the configured limit.
        crash = [e for e in rt.events(handle.id) if e.kind == EventKind.crash]
        assert any(
            e.payload.get("cap") == "iterations"
            and e.payload.get("limit") == 1
            for e in crash
        )
        # Mesh alive: a sibling spawned after still completes (its acceptance
        # is met in a single step, before the iteration cap trips).
        sibling = rt.spawn(
            "sibling",
            acceptance=("ok",),
            driver=MockDriver(["complete('fine')"]),
        )
        assert sibling.await_().status == AgentStatus.completed
    finally:
        rt.stop()


def test_d2d_cancellation_grace(tmp_path):
    """D2d: cancellation lands between steps — kill() + rollback + settle
    cancelled. The runner is never resumed (advance returns 'abandoned') and
    the workspace is rolled back (no partial mutation); the mesh stays alive."""
    rt = _pumped_runtime(tmp_path, max_turn_seconds=1.0)
    try:
        handle = rt.spawn(
            "slow",
            driver=MockDriver(["x = 'partial'\nwhile True: pass"]),
        )
        # Wait for the step to start (turn_started is emitted before advance).
        assert wait_for(
            lambda: any(e.kind == EventKind.turn_started for e in rt.events(handle.id))
        )
        res = handle.cancel("stop now")
        assert res.done and not res.ok
        assert wait_for(lambda: rt.poll(handle.id) == AgentStatus.cancelled)
        # The runner was killed: advance returns abandoned (never resumed).
        assert rt.repl_engine.advance(handle.id).kind == "abandoned"
        # The workspace was rolled back: no partial mutation from the step.
        assert "x" not in rt.repl_engine.globals_for(handle.id)
        # Mesh alive: a sibling spawned after still completes.
        sibling = rt.spawn("sibling", driver=MockDriver(["complete('fine')"]))
        assert sibling.await_().status == AgentStatus.completed
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# D3 — yield Await without step-budget burn
# --------------------------------------------------------------------------- #


def test_d3_yield_await_no_step_budget_burn(tmp_path):
    """D3: ``yield Await(child)`` parks the parent without burning its step
    budget. The parent's runner is parked while the slow child sleeps; a fast
    sibling completes during the wait (the parent's loop stayed responsive)
    and the parent's step count does not advance while parked."""
    rt = _pumped_runtime(tmp_path)
    try:
        slow_child = MockDriver.single(
            "import time\ntime.sleep(1.0)\ncomplete('slow child done')"
        )
        fast_child = MockDriver.single("complete('fast sibling done')")
        parent = rt.spawn(
            "parent",
            driver=MockDriver(
                [
                    "__runner = '''def __runner__(ctx):\n"
                    "    c1 = spawn('slow child', driver=slow_child)\n"
                    "    c2 = spawn('fast sibling', driver=fast_child)\n"
                    "    ctx['state']['await_started'] = True\n"
                    "    yield Await(c1)\n"
                    "    complete('parent done')\n"
                    "'''\n"
                ]
            ),
            namespace={"slow_child": slow_child, "fast_child": fast_child},
        )
        # The parent's runner is parked on Await(c1) once the flag is set.
        assert wait_for(
            lambda: rt.repl_engine.globals_for(parent.id)
            .get("state", {})
            .get("await_started")
        )
        slow_id, fast_id = rt.children_of(parent.id)
        # The fast sibling completes during the wait...
        assert rt.await_(fast_id).status == AgentStatus.completed
        # ...and its completion is delivered to the parent's stream while the
        # parent is still parked (the parent's loop stayed responsive).
        assert wait_for(
            lambda: any(c.agent_id == fast_id for c in rt.completions(parent.id))
        )
        assert rt.poll(parent.id) == AgentStatus.running
        # The parent's runner was NOT advanced while parked: no new steps
        # (the parent's own observe() drains its stream, so assert on the
        # absence of NEW steps rather than an absolute count).
        time.sleep(0.2)
        assert not any(
            e.kind == EventKind.turn_started and e.payload.get("step", 0) > 2
            for e in rt.events(parent.id)
        )
        # Once the slow child settles, the parent resumes and completes.
        completion = parent.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "parent done"
    finally:
        rt.stop()


def test_d3_await_backcompat_default_loop(tmp_path):
    """D3 back-compat: the blocking ``await_`` still works on the default
    loop (a parent can block on a child and complete)."""
    rt = _pumped_runtime(tmp_path)
    try:
        parent = rt.spawn(
            "parent",
            driver=MockDriver(
                [
                    "c1 = spawn('child', driver=MockDriver.single(\"complete('child ok')\"))\n"
                    "r = await_(c1)\n"
                    "complete('parent saw ' + r.status.value)\n"
                ]
            ),
        )
        completion = parent.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "parent saw completed"
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# D4 — deterministic default fabrications
# --------------------------------------------------------------------------- #


def test_d4_default_fabrication_plain_spawn(tmp_path):
    """D4: a plain spawn with a MockDriver completes through the default
    loop — the default __runner/decide/context reproduce today's behavior
    exactly."""
    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn("do it", driver=MockDriver(["complete('all good')"]))
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "all good"
        assert rt.result(handle.id).ok
        # The default fabrication is intact in the workspace.
        ws = rt.repl_engine.globals_for(handle.id)
        assert ws["__runner"] == DEFAULT_RUNNER_SOURCE
        assert callable(ws["decide"])
        assert ws["context"].agent_id == handle.id
    finally:
        rt.stop()


def test_d4_ensure_fabrication_reseeds(tmp_path):
    """D4: ensure_fabrication re-seeds a broken fabrication (__runner = 42)
    between steps, emits a crash event with the reseeded names, and the agent
    continues on the default loop."""
    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn(
            "breaker",
            driver=MockDriver(["__runner = 42\n", "complete('recovered')\n"]),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "recovered"
        ws = rt.repl_engine.globals_for(handle.id)
        # The workspace citizen was re-seeded to the default source.
        assert ws["__runner"] == DEFAULT_RUNNER_SOURCE
        # The re-seed emitted a crash event with the reseeded names; the
        # default runner's observe() drained it into the state digest.
        digest = ws["state"]["digests"]["events"]
        assert any(
            e.kind == EventKind.crash
            and e.payload.get("fabrication_reseeded") == ["__runner"]
            for e in digest
        )
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# D5 — guardrail placement
# --------------------------------------------------------------------------- #


def test_d5a_normative_guardrails_visible_context_in(tmp_path):
    """D5a: parent-imposed guardrails arrive as visible context-in at
    delegation (spawn(..., namespace={'guardrails': ...}) — the existing
    delegation seam). The child sees them in its workspace and internalizes
    them into its self-authored context.guardrails store."""
    rt = _pumped_runtime(tmp_path)
    try:
        parent = rt.spawn(
            "parent",
            driver=MockDriver(
                [
                    "c1 = spawn('child', driver=MockDriver.single(\"state['seen_guardrails'] = dict(guardrails)\\ncontext.guardrails.update(guardrails)\\ncomplete('internalized')\\n\"), namespace={'guardrails': {'budget': 3, 'max_steps': 2}})\n"
                    "complete('spawned')\n"
                ]
            ),
        )
        parent.await_()
        child_id = rt.children_of(parent.id)[0]
        assert rt.await_(child_id).status == AgentStatus.completed
        ws = rt.repl_engine.globals_for(child_id)
        # The parent-imposed guardrails arrived as visible context-in.
        assert ws["guardrails"] == {"budget": 3, "max_steps": 2}
        # The child internalized them (visible in its own context store).
        assert ws["state"]["seen_guardrails"] == {"budget": 3, "max_steps": 2}
        assert ws["context"].guardrails == {"budget": 3, "max_steps": 2}
    finally:
        rt.stop()


def test_d5b_operational_tripwire_pump_evaluated(tmp_path):
    """D5b: an operational tripwire (max_iterations) is evaluated by the PUMP
    between steps and fires even though the agent's code never checks it. The
    agent is contained; the mesh stays alive."""
    from dhc.config import HarnessConfig, SafetyConfig

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(max_iterations=1)),
    )
    try:
        handle = rt.spawn(
            "looper",
            driver=MockDriver(
                [
                    "state['tripwire_never_checked'] = True\n"
                    "context.guardrails['budget'] = 1\n",
                    "complete('second step')\n",
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.failed
        assert "cap exceeded" in completion.reason
        assert "iterations" in completion.reason
        # The agent's code never checked the cap (it never called caps()).
        ws = rt.repl_engine.globals_for(handle.id)
        assert ws["state"].get("tripwire_never_checked") is True
        # The self-authored guardrail store is ordinary workspace data.
        assert ws["context"].guardrails.get("budget") == 1
        # A crash event was emitted with the cap name and limit.
        crash = [e for e in rt.events(handle.id) if e.kind == EventKind.crash]
        assert any(
            e.payload.get("cap") == "iterations" and e.payload.get("limit") == 1
            for e in crash
        )
        # Mesh alive: a sibling spawned after still completes (its acceptance
        # is met in a single step, before the iteration cap trips).
        sibling = rt.spawn(
            "sibling",
            acceptance=("ok",),
            driver=MockDriver(["complete('fine')"]),
        )
        assert sibling.await_().status == AgentStatus.completed
    finally:
        rt.stop()


def test_d5c_reaction_ships_to_parent(tmp_path):
    """D5c: a reaction ships as a completion-style event on the parent's
    stream and is executed in the parent's REPL (the on_done callback runs in
    the parent's worker loop). The child does not execute its own
    termination: it settles failed (its reaction is the settlement) and never
    cancels itself."""
    rt = _pumped_runtime(tmp_path)
    try:
        reactions = []
        parent = rt.spawn(
            "parent",
            driver=MockDriver(
                [
                    "c1 = spawn('child', driver=MockDriver.single(\"fail('terminate')\"), "
                    "on_done=lambda c: reactions.append((c.agent_id, c.status, c.reason)))\n"
                    "complete('spawned')\n"
                ]
            ),
            namespace={"reactions": reactions},
        )
        parent.await_()
        child_id = rt.children_of(parent.id)[0]
        rt.await_(child_id)
        # The parent received the child's completion-style event on its stream.
        completions = rt.completions(parent.id)
        assert len(completions) == 1
        assert completions[0].agent_id == child_id
        assert completions[0].status == AgentStatus.failed
        assert completions[0].reason == "terminate"
        # The reaction was executed in the parent's REPL (the callback ran).
        assert reactions == [(child_id, AgentStatus.failed, "terminate")]
        # The child did not execute its own termination: it settled failed
        # (its reaction was the settlement), never cancelling itself.
        assert rt.poll(child_id) == AgentStatus.failed
        # The parent stayed alive and completed after the reaction.
        assert rt.poll(parent.id) == AgentStatus.completed
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# Runaway containment (the IMP containment table)
# --------------------------------------------------------------------------- #


def test_runaway_containment_mesh_alive(tmp_path):
    """Runaway containment: a ``while True: pass`` loop is bounded by the
    step timeout — timeout -> rollback -> settle — with the mesh alive. The
    runaway settles timeout within a few seconds, a sibling spawned after
    still completes, and the workspace was rolled back (no partial state)."""
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
        # A timeout event was emitted.
        assert any(e.kind == EventKind.timeout for e in rt.events(runaway.id))
        # The workspace was rolled back: the runaway step's partial mutation
        # is gone (the engine abandoned the runner and restored the snapshot).
        assert "x" not in rt.repl_engine.globals_for(runaway.id)
        # A sibling spawned after still completes (mesh alive).
        sibling = rt.spawn("sibling", driver=MockDriver(["complete('fine')"]))
        assert sibling.await_().status == AgentStatus.completed
    finally:
        rt.stop()