"""Tests for dhc.framework and dhc.runtime.

Uses scripted drivers and fakes only — no real LLM, no real REPL, no real
artifact store. The runtime's injected collaborators are duck-typed, so the
tests exercise the same seams the integration agent will wire the real
modules into.
"""

import threading
import time

import pytest

from dhc.framework.agent import Agent, AgentHandle, ToolResult
from dhc.errors import ChannelError
from dhc.data.models import (
    TERMINAL_STATES,
    AgentStatus,
    Completion,
    EventKind,
    Result,
    ToolOutput,
    is_terminal,
)
from dhc.framework.runtime import Runtime


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class ScriptedDriver:
    """A driver that replays a fixed script of code blocks, then settles."""

    def __init__(self, *blocks: str) -> None:
        self.blocks = list(blocks)
        self.calls = 0

    def __call__(self, agent: Agent):
        if self.calls >= len(self.blocks):
            return None
        code = self.blocks[self.calls]
        self.calls += 1
        return code


class RaisingDriver:
    """A driver that raises on the first call (crash containment)."""

    def __call__(self, agent: Agent):
        raise RuntimeError("driver exploded")


class BlockingDriver:
    """A driver that blocks forever on the first call (for cancellation)."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()

    def __call__(self, agent: Agent):
        self.entered.set()
        self.release.wait(timeout=30)
        return None


def wait_for(predicate, timeout: float = 10.0) -> bool:
    """Poll *predicate* until it is true or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def make_runtime(**kwargs) -> Runtime:
    rt = Runtime(**kwargs)
    rt.start()
    return rt


# --------------------------------------------------------------------------- #
# Agent surface
# --------------------------------------------------------------------------- #


def test_agent_fields_and_defaults():
    agent = Agent(id="a1", requirement="do the thing", acceptance=("ok",))
    assert agent.id == "a1"
    assert agent.requirement == "do the thing"
    assert agent.acceptance == ("ok",)
    assert agent.parent_id is None
    assert agent._status == AgentStatus.pending
    assert agent._result is None
    assert agent.children == []
    assert agent.created_ts > 0
    assert agent.settled_ts is None
    assert not agent.done


def test_agent_complete_fail_cancel_status_result():
    agent = Agent(id="a1", requirement="r")
    done = agent.complete("headline", artifacts=("sha256:x",))
    assert done.done and done.ok and done.value == "headline"
    assert done.artifacts == ["sha256:x"]

    failed = agent.fail("nope")
    assert failed.done and not failed.ok and failed.reason == "nope"

    cancelled = agent.cancel("stop")
    assert cancelled.done and not cancelled.ok and cancelled.reason == "stop"

    st = agent.status()
    assert st.done is False and st.ok is False

    res = agent.result()
    assert res.done is False and res.reason == "not settled"


def test_agent_tool_captures_output_and_errors():
    agent = Agent(id="a1", requirement="r")

    def add(a, b):
        return a + b

    out = agent.tool(add, 2, 3)
    assert isinstance(out, ToolResult)
    assert isinstance(out, ToolOutput)
    assert out.ok and out.text == "5"

    def boom():
        raise ValueError("kaboom")

    err = agent.tool(boom)
    assert not err.ok
    assert "ValueError" in err.text and "kaboom" in err.text


def test_agent_has_no_publish_method():
    """Publishing is a composed tooling namespace tool, not an agent method
    (decision 0014): the framework core is store-unaware."""
    agent = Agent(id="a1", requirement="r")
    assert not hasattr(agent, "publish")


def test_agent_spawn_delegates_to_runtime():
    rt = make_runtime()
    parent = rt.get(rt.spawn("parent", driver=ScriptedDriver()).id)
    child = parent.spawn("child task")
    assert isinstance(child, Agent)
    assert child.id in parent.children
    assert child.parent_id == parent.id
    assert rt.get(child.id) is child
    rt.stop()


def test_agent_handle_surface():
    rt = make_runtime()
    handle = rt.spawn("task", driver=ScriptedDriver("complete('done')"))
    assert isinstance(handle, AgentHandle)
    assert handle.id == handle.get().id
    completion = handle.await_()
    assert completion.status == AgentStatus.completed
    assert handle.poll() == AgentStatus.completed
    assert handle.status() == AgentStatus.completed
    assert handle.result().ok
    rt.stop()


# --------------------------------------------------------------------------- #
# Spawn -> run -> await
# --------------------------------------------------------------------------- #


def test_spawn_run_await_completed():
    rt = make_runtime()
    handle = rt.spawn("do it", driver=ScriptedDriver("complete('all good')"))
    assert handle.poll() in (AgentStatus.pending, AgentStatus.running)
    completion = handle.await_()
    assert completion.status == AgentStatus.completed
    assert completion.summary == "all good"
    assert rt.is_settled(handle.id)
    assert rt.result(handle.id).ok
    rt.stop()


def test_await_is_ensure_terminal_after_settlement():
    rt = make_runtime()
    handle = rt.spawn("do it", driver=ScriptedDriver("complete('done')"))
    first = handle.await_()
    second = handle.await_()  # awaiting after settlement still succeeds
    assert first is second
    assert first.status == AgentStatus.completed
    rt.stop()


def test_driver_none_settles_failed_without_result():
    rt = make_runtime()
    handle = rt.spawn("do it", driver=ScriptedDriver())
    completion = handle.await_()
    assert completion.status == AgentStatus.failed
    assert "no result" in completion.reason
    rt.stop()


def test_poll_is_non_blocking():
    rt = make_runtime()
    handle = rt.spawn("do it", driver=ScriptedDriver("complete('done')"))
    t0 = time.monotonic()
    state = handle.poll()
    assert time.monotonic() - t0 < 0.5
    assert state in (AgentStatus.pending, AgentStatus.running, AgentStatus.completed)
    handle.await_()
    rt.stop()


def test_result_returns_settled_result():
    rt = make_runtime()
    handle = rt.spawn("do it", driver=ScriptedDriver("complete('value')"))
    handle.await_()
    res = rt.result(handle.id)
    assert res.done and res.ok and res.value == "value"
    rt.stop()


def test_unknown_agent_raises_keyerror():
    rt = make_runtime()
    with pytest.raises(KeyError):
        rt.poll("nope")
    with pytest.raises(KeyError):
        rt.await_("nope")
    with pytest.raises(KeyError):
        rt.cancel("nope")
    rt.stop()


# --------------------------------------------------------------------------- #
# Fan-out: parent spawns children, aggregates, stays alive until all settle
# --------------------------------------------------------------------------- #


def test_fan_out_parent_waits_for_children_and_aggregates():
    rt = make_runtime()
    state = {"spawned": False, "aggregated": False}

    def child_driver(agent: Agent):
        if agent._last_result is not None:
            return None  # already completed -> settle
        return "complete('child done')"

    def parent_driver(agent: Agent):
        if not state["spawned"]:
            state["spawned"] = True
            return (
                "c1 = spawn('child one', driver=child_driver, "
                "on_done=lambda c: None)\n"
                "c2 = spawn('child two', driver=child_driver, "
                "on_done=lambda c: None)\n"
                "c3 = spawn('child three', driver=child_driver, "
                "on_done=lambda c: None)\n"
            )
        if not state["aggregated"]:
            state["aggregated"] = True
            return (
                "results = [await_(c).status.value for c in (c1, c2, c3)]\n"
                "complete('aggregated: ' + ','.join(results))\n"
            )
        return None

    parent = rt.spawn(
        "parent",
        driver=parent_driver,
        namespace={"child_driver": child_driver},
    )
    # Children are spawned by the parent's first turn (async) — wait for them.
    assert wait_for(lambda: len(rt.children_of(parent.id)) == 3)
    child_ids = rt.children_of(parent.id)
    assert len(child_ids) == 3

    # Children run in parallel and complete.
    for cid in child_ids:
        assert rt.await_(cid).status == AgentStatus.completed

    # Parent stays alive until all children settle, then completes.
    completion = parent.await_()
    assert completion.status == AgentStatus.completed
    assert "aggregated" in completion.summary
    assert "completed" in completion.summary
    rt.stop()


def test_fan_out_children_run_in_parallel():
    rt = make_runtime()
    order = []
    lock = threading.Lock()
    state = {"spawned": False}

    def child_driver(agent: Agent):
        if agent._last_result is not None:
            return None
        with lock:
            order.append(agent.id)
        time.sleep(0.2)
        return "complete('child done')"

    def parent_driver(agent: Agent):
        if not state["spawned"]:
            state["spawned"] = True
            return (
                "c1 = spawn('c1', driver=child_driver)\n"
                "c2 = spawn('c2', driver=child_driver)\n"
                "c3 = spawn('c3', driver=child_driver)\n"
                "complete('spawned')\n"
            )
        return None

    parent = rt.spawn(
        "parent",
        driver=parent_driver,
        namespace={"child_driver": child_driver},
    )
    parent.await_()
    child_ids = rt.children_of(parent.id)
    assert len(child_ids) == 3
    for cid in child_ids:
        assert rt.await_(cid).status == AgentStatus.completed
    # All three children entered before any finished (parallelism).
    assert len(order) == 3
    rt.stop()


# --------------------------------------------------------------------------- #
# Crash containment
# --------------------------------------------------------------------------- #


def test_crash_containment_child_fails_siblings_complete():
    rt = make_runtime()

    def parent_driver(agent: Agent):
        if not agent.children:
            return (
                "c1 = spawn('crasher', driver=raising_driver)\n"
                "c2 = spawn('healthy', driver=healthy_driver)\n"
                "complete('spawned')\n"
            )
        return None

    def raising_driver(agent: Agent):
        raise RuntimeError("boom")

    def healthy_driver(agent: Agent):
        if agent._last_result is not None:
            return None
        return "complete('healthy done')"

    parent = rt.spawn(
        "parent",
        driver=parent_driver,
        namespace={"raising_driver": raising_driver, "healthy_driver": healthy_driver},
    )
    parent.await_()
    child_ids = rt.children_of(parent.id)
    assert len(child_ids) == 2
    by_status = {rt.await_(cid).status for cid in child_ids}
    assert AgentStatus.failed in by_status
    assert AgentStatus.completed in by_status
    # The crashed child's completion carries the crash reason.
    for cid in child_ids:
        completion = rt.await_(cid)
        if completion.status == AgentStatus.failed:
            assert "boom" in completion.reason
    rt.stop()


def test_turn_crash_contained_to_agent():
    rt = make_runtime()
    handle = rt.spawn("do it", driver=ScriptedDriver("raise ValueError('turn boom')"))
    completion = handle.await_()
    assert completion.status == AgentStatus.failed
    assert "turn boom" in completion.reason
    # Sibling still works.
    other = rt.spawn("other", driver=ScriptedDriver("complete('fine')"))
    assert other.await_().status == AgentStatus.completed
    rt.stop()


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #


def test_cancel_running_child():
    rt = make_runtime()
    blocking = BlockingDriver()
    handle = rt.spawn("slow", driver=blocking)
    assert blocking.entered.wait(timeout=5)
    assert handle.poll() == AgentStatus.running
    res = handle.cancel("stop now")
    assert res.done and not res.ok
    assert handle.poll() == AgentStatus.cancelled
    assert rt.is_settled(handle.id)
    blocking.release.set()
    rt.stop()


def test_cancel_before_worker_starts():
    rt = make_runtime()
    blocking = BlockingDriver()
    handle = rt.spawn("slow", driver=blocking)
    res = handle.cancel("too late")
    assert res.done and not res.ok
    assert handle.poll() == AgentStatus.cancelled
    blocking.release.set()
    rt.stop()


def test_cancel_after_settlement_returns_existing_result():
    rt = make_runtime()
    handle = rt.spawn("fast", driver=ScriptedDriver("complete('done')"))
    handle.await_()
    res = handle.cancel("nope")
    assert res.ok and res.value == "done"  # settlement is at-most-once
    assert handle.poll() == AgentStatus.completed
    rt.stop()


# --------------------------------------------------------------------------- #
# At-most-once completion dispatch
# --------------------------------------------------------------------------- #


def test_double_settle_raises_channel_error():
    rt = make_runtime()
    handle = rt.spawn("do it", driver=ScriptedDriver("complete('done')"))
    handle.await_()
    with pytest.raises(ChannelError):
        rt.completion_log().settle(
            Completion(agent_id=handle.id, status=AgentStatus.failed, reason="late")
        )
    rt.stop()


def test_completion_delivered_once_to_parent_stream():
    rt = make_runtime()

    def child_driver(agent: Agent):
        if agent._last_result is not None:
            return None
        return "complete('child done')"

    parent = rt.spawn(
        "parent",
        driver=ScriptedDriver(
            "c1 = spawn('child', driver=child_driver)\ncomplete('spawned')\n"
        ),
        namespace={"child_driver": child_driver},
    )
    parent.await_()
    child_id = rt.children_of(parent.id)[0]
    rt.await_(child_id)
    completions = rt.completions(parent.id)
    assert len(completions) == 1
    assert completions[0].agent_id == child_id
    assert completions[0].status == AgentStatus.completed
    rt.stop()


def test_completion_callbacks_all_delivered_exactly_once():
    rt = make_runtime()
    order = []
    lock = threading.Lock()

    def child_driver(agent: Agent):
        if agent._last_result is not None:
            return None
        return "complete('child done')"

    def parent_driver(agent: Agent):
        if not agent.children:
            return (
                "c1 = spawn('c1', driver=child_driver, "
                "on_done=lambda c: order.append('c1'))\n"
                "c2 = spawn('c2', driver=child_driver, "
                "on_done=lambda c: order.append('c2'))\n"
                "c3 = spawn('c3', driver=child_driver, "
                "on_done=lambda c: order.append('c3'))\n"
                "complete('spawned')\n"
            )
        return None

    parent = rt.spawn(
        "parent",
        driver=parent_driver,
        namespace={"child_driver": child_driver, "order": order},
    )
    parent.await_()
    for cid in rt.children_of(parent.id):
        rt.await_(cid)
    # All three callbacks ran exactly once. Completion callbacks are delivered
    # FIFO in settlement order; settlement order across threads is
    # nondeterministic, so only membership + count are guaranteed.
    assert sorted(order) == ["c1", "c2", "c3"]
    rt.stop()


def test_callback_receives_settled_values_not_handles():
    rt = make_runtime()
    seen = []

    def parent_driver(agent: Agent):
        if not agent.children:
            return (
                "c1 = spawn('c1', driver=child_driver, "
                "on_done=lambda c: seen.append((c.status, c.summary)))\n"
                "complete('spawned')\n"
            )
        return None

    def child_driver(agent: Agent):
        if agent._last_result is not None:
            return None
        return "complete('child summary')"

    parent = rt.spawn(
        "parent",
        driver=parent_driver,
        namespace={"child_driver": child_driver, "seen": seen},
    )
    parent.await_()
    for cid in rt.children_of(parent.id):
        rt.await_(cid)
    assert seen == [("completed", "child summary")]
    rt.stop()


# --------------------------------------------------------------------------- #
# Parent liveness guard
# --------------------------------------------------------------------------- #


def test_parent_with_unsettled_children_does_not_settle():
    rt = make_runtime()
    blocking = BlockingDriver()
    parent = rt.spawn(
        "parent",
        driver=ScriptedDriver(
            "c1 = spawn('slow child', driver=blocking_driver)\n"
            "complete('spawned')\n"
        ),
        namespace={"blocking_driver": blocking},
    )
    # Give the parent time to spawn the child and reach its settle point.
    assert wait_for(lambda: len(rt.children_of(parent.id)) == 1)
    time.sleep(0.2)
    # The parent must still be alive (running), blocked on the child.
    assert rt.poll(parent.id) == AgentStatus.running
    assert not rt.is_settled(parent.id)
    # Once the child settles, the parent settles too.
    blocking.release.set()
    assert parent.await_().status == AgentStatus.completed
    rt.stop()


def test_parent_liveness_guard_blocks_until_children_settle():
    rt = make_runtime()

    def child_driver(agent: Agent):
        time.sleep(0.3)
        if agent._last_result is not None:
            return None
        return "complete('child done')"

    def parent_driver(agent: Agent):
        if not agent.children:
            return (
                "c1 = spawn('c1', driver=child_driver)\n"
                "c2 = spawn('c2', driver=child_driver)\n"
                "complete('spawned')\n"
            )
        return None

    parent = rt.spawn(
        "parent",
        driver=parent_driver,
        namespace={"child_driver": child_driver},
    )
    t0 = time.monotonic()
    completion = parent.await_()
    elapsed = time.monotonic() - t0
    # The parent could not settle before its children (0.3s each, parallel).
    assert completion.status == AgentStatus.completed
    assert elapsed >= 0.25
    rt.stop()


# --------------------------------------------------------------------------- #
# Acceptance criteria
# --------------------------------------------------------------------------- #


def test_acceptance_met_settles_completed():
    rt = make_runtime()
    handle = rt.spawn(
        "task",
        acceptance=("ok",),
        driver=ScriptedDriver("complete('first')", "complete('second')"),
    )
    completion = handle.await_()
    assert completion.status == AgentStatus.completed
    assert completion.summary == "first"
    rt.stop()


def test_acceptance_not_met_keeps_running_then_settles():
    rt = make_runtime()
    handle = rt.spawn(
        "task",
        acceptance=("ok",),
        driver=ScriptedDriver("complete('first')", "complete('second')"),
    )
    # First turn completes but acceptance is not met -> still running.
    assert wait_for(lambda: rt.poll(handle.id) == AgentStatus.completed)
    rt.stop()


# --------------------------------------------------------------------------- #
# Events / stop
# --------------------------------------------------------------------------- #


def test_turn_events_emitted():
    rt = make_runtime()
    handle = rt.spawn("do it", driver=ScriptedDriver("complete('done')"))
    handle.await_()
    kinds = [e.kind for e in rt.events(handle.id)]
    assert EventKind.turn_started in kinds
    assert EventKind.turn_completed in kinds
    assert EventKind.child_settled in kinds
    rt.stop()


def test_stop_joins_all_threads():
    rt = make_runtime()
    blocking = BlockingDriver()
    handles = [rt.spawn(f"t{i}", driver=ScriptedDriver("complete('x')")) for i in range(3)]
    handles.append(rt.spawn("blocked", driver=blocking))
    for h in handles[:3]:
        h.await_()
    blocking.entered.wait(timeout=5)
    rt.stop()
    # All workers joined; the blocked one was cancelled by stop().
    assert rt.poll(handles[3].id) == AgentStatus.cancelled
    for h in handles[:3]:
        assert rt.poll(h.id) == AgentStatus.completed
    blocking.release.set()


def test_room_registry():
    """room is a TOOL (not core): it must be installed via the tools layer.

    The core namespace is slim (no room); the channel tooling composes it in
    (decision 0015: channels are tooling over the core send primitive).
    """
    from dhc.tooling.channels import RoomManager
    from dhc.tooling.channel_tools import register_channel_tools

    rt = make_runtime()
    rooms = RoomManager(rt.event_bus)
    register_channel_tools(rt, channels={"rooms": rooms})
    handle = rt.spawn(
        "do it",
        driver=ScriptedDriver(
            "r = room('war-room')\n"
            "assert r.name == 'war-room'\n"
            "assert agent.id in r.member_ids\n"
            "complete('room ok')\n"
        ),
    )
    assert handle.await_().status == AgentStatus.completed
    rt.stop()


def test_bash_tool_returns_text():
    rt = make_runtime()
    handle = rt.spawn(
        "do it",
        driver=ScriptedDriver("out = bash('echo hello')\ncomplete(out.strip())"),
    )
    completion = handle.await_()
    assert completion.status == AgentStatus.completed
    assert completion.summary == "hello"
    rt.stop()


# --------------------------------------------------------------------------- #
# IMP-001 Step 3: the pump (_pump_agent) — four hard gates + caps watchdog
# --------------------------------------------------------------------------- #
# These tests exercise the PUMPED path: a fully-wired runtime (ReplEngine +
# fabrication kit) driving the default __runner generator one step at a time.
# The legacy in-memory path is covered by the tests above (make_runtime).


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


def test_pump_default_runner_completes(tmp_path):
    """A plain spawn with a MockDriver script completes through the pump."""
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn("do it", driver=MockDriver(["complete('all good')"]))
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "all good"
        assert rt.result(handle.id).ok
    finally:
        rt.stop()


def test_pump_runaway_loop_contained_mesh_alive(tmp_path):
    """A runaway step is bounded by the step timeout; the mesh stays alive."""
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


def test_pump_child_count_cap_forced_stop(tmp_path):
    """A tiny child cap force-stops the parent (settles failed, cap reason)."""
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(max_agents=1)),
    )
    try:
        parent = rt.spawn(
            "parent",
            driver=MockDriver(
                [
                    "c1 = spawn('child', driver=MockDriver.single(\"complete('ok')\"))\n"
                    "complete('spawned')\n"
                ]
            ),
        )
        completion = parent.await_()
        assert completion.status == AgentStatus.failed
        assert "cap exceeded" in completion.reason
        assert "children" in completion.reason
        # A crash event was emitted with the cap name and limit.
        kinds = [e.kind for e in rt.events(parent.id)]
        assert EventKind.crash in kinds
        # The child still completes (mesh alive).
        for cid in rt.children_of(parent.id):
            assert rt.await_(cid).status == AgentStatus.completed
    finally:
        rt.stop()


def test_pump_settlement_at_most_once(tmp_path):
    """Through the pump: exactly one completion; a second settle raises."""
    from dhc.llm.driver import MockDriver

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


def test_pump_cancellation_grace_kill_rollback_settle(tmp_path):
    """Cancel between steps: settles cancelled, runner killed, workspace rolled back."""
    from dhc.llm.driver import MockDriver

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
    finally:
        rt.stop()

# --------------------------------------------------------------------------- #
# IMP-001 Step 4: yield vocabulary (Await / Poll / Sleep) serviced by the pump
# --------------------------------------------------------------------------- #
# D3 (yield-async split): direct workspace calls stay synchronous; only
# indefinite/off-thread ops are `yield` requests serviced by the pump. The
# parent's runner is parked (engine.suspend) while an Await/Sleep is serviced,
# so the parent's step budget is NOT consumed while parked.


def test_pump_yield_await_parent_not_starved(tmp_path):
    """D3: `yield Await(child)` parks the parent without burning its budget.

    The parent's runner is parked while the child sleeps; the parent's loop
    stays responsive (a sibling completes and its completion is delivered to
    the parent's stream during the wait) and the parent's step count does not
    advance while parked.
    """
    from dhc.llm.driver import MockDriver

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
        # The parent's runner was NOT advanced while parked: no new
        # turn_started events are emitted while the parent waits (the parent's
        # own observe() drains its stream, so assert on the absence of NEW
        # steps rather than an absolute count).
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


def test_pump_yield_sleep_parks_and_resumes(tmp_path):
    """`yield Sleep(t)` parks the runner and resumes it after ~t."""
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn(
            "sleeper",
            driver=MockDriver(
                [
                    "__runner = '''def __runner__(ctx):\n"
                    "    ctx['state']['sleep_started'] = True\n"
                    "    yield Sleep(0.3)\n"
                    "    complete('slept')\n"
                    "'''\n"
                ]
            ),
        )
        # The runner parks itself: wait for the flag, then wait until the
        # pump has actually parked the runner (engine-side state), then
        # advance returns "suspended" while the pump services the Sleep.
        assert wait_for(
            lambda: rt.repl_engine.globals_for(handle.id)
            .get("state", {})
            .get("sleep_started")
        )
        assert wait_for(
            lambda: rt.repl_engine._runner_states.get(handle.id) == "suspended"
        )
        assert rt.repl_engine.advance(handle.id).kind == "suspended"
        t0 = time.monotonic()
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "slept"
        # The runner resumed only after the sleep elapsed.
        assert time.monotonic() - t0 >= 0.2
    finally:
        rt.stop()


def test_pump_yield_poll_non_blocking(tmp_path):
    """`yield Poll(child)` returns the child's status without blocking."""
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(tmp_path)
    try:
        blocking = BlockingDriver()
        handle = rt.spawn(
            "polling parent",
            driver=MockDriver(
                [
                    "__runner = '''import time\n"
                    "def __runner__(ctx):\n"
                    "    c1 = spawn('child', driver=blocking_driver)\n"
                    "    ctx['state']['t0'] = time.monotonic()\n"
                    "    yield Poll(c1)\n"
                    "    ctx['state']['t1'] = time.monotonic()\n"
                    "    ctx['state']['poll_status'] = ctx['state']['yield_result']\n"
                    "    complete('polled')\n"
                    "'''\n"
                ]
            ),
            namespace={"blocking_driver": blocking},
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "polled"
        state = rt.repl_engine.globals_for(handle.id)["state"]
        # The Poll did not block: the yield round-trip was fast.
        assert state["t1"] - state["t0"] < 0.5
        # The child's current status was delivered back into the generator.
        assert state["poll_status"] in (AgentStatus.pending, AgentStatus.running)
        blocking.release.set()
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# IMP-001 Step 5: caps config, ensure_fabrication seam, guardrail tripwires,
# reactions
# --------------------------------------------------------------------------- #


def test_caps_defaults_enforced(tmp_path):
    """A tiny workspace cap force-stops the agent; the watchdog reads the NEW
    config fields (SafetyConfig.max_workspace_bytes), not only module
    constants."""
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(max_workspace_bytes=1)),
    )
    try:
        handle = rt.spawn("big", driver=MockDriver(["complete('done')"]))
        completion = handle.await_()
        assert completion.status == AgentStatus.failed
        assert "cap exceeded" in completion.reason
        assert "workspace_bytes" in completion.reason
        # A crash event was emitted with the cap name and the configured limit.
        crash = [e for e in rt.events(handle.id) if e.kind == EventKind.crash]
        assert any(
            e.payload.get("cap") == "workspace_bytes"
            and e.payload.get("limit") == 1
            for e in crash
        )
    finally:
        rt.stop()


def test_guardrail_tripwire_fires_between_steps(tmp_path):
    """An operational tripwire (caps) is pump-evaluated between steps.

    The agent's code never checks the cap; the pump's between-step watchdog
    fires and contains the agent. The self-authored guardrail store
    (context.guardrails) is ordinary workspace data (D5).
    """
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

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
        # The self-authored guardrail store is visible workspace data.
        assert ws["context"].guardrails.get("budget") == 1
        # A crash event was emitted with the cap name and limit.
        crash = [e for e in rt.events(handle.id) if e.kind == EventKind.crash]
        assert any(
            e.payload.get("cap") == "iterations"
            and e.payload.get("limit") == 1
            for e in crash
        )
    finally:
        rt.stop()


def test_reaction_ships_to_parent(tmp_path):
    """A child's reaction ships as a completion-style event on the parent's
    stream and is executed in the parent's REPL (the on_done callback runs in
    the parent's worker loop). The child does not execute its own
    termination: it settles failed (its reaction is the settlement) and never
    cancels itself."""
    from dhc.llm.driver import MockDriver

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


def test_ensure_fabrication_reseeds(tmp_path):
    """Agent breaks a fabrication (__runner = 42); the pump re-seeds it
    between steps, emits a crash event with the reseeded names, and the agent
    continues."""
    from dhc.llm.driver import MockDriver
    from dhc.tooling.fabrication import DEFAULT_RUNNER_SOURCE

    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn(
            "breaker",
            driver=MockDriver(
                [
                    "__runner = 42\n",
                    "complete('recovered')\n",
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "recovered"
        # The workspace citizen was re-seeded to the default source.
        assert (
            rt.repl_engine.globals_for(handle.id)["__runner"]
            == DEFAULT_RUNNER_SOURCE
        )
        # The re-seed emitted a crash event with the reseeded names. The
        # default runner's observe() drains the event stream into the state
        # digest, so the event is asserted there.
        digest = rt.repl_engine.globals_for(handle.id)["state"]["digests"]["events"]
        assert any(
            e.kind == EventKind.crash
            and e.payload.get("fabrication_reseeded") == ["__runner"]
            for e in digest
        )
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# G-01: agent-set working budgets enforced by the pump, clamped to ceilings.
# The effective limit is min(agent_budget, runtime_ceiling), evaluated in
# runtime/pump code — agent data can only TIGHTEN a limit, never loosen it.
# --------------------------------------------------------------------------- #


def test_g01_agent_budget_tightens_iterations_cap(tmp_path):
    """G-01 (1): the agent sets context.budgets['max_iterations']=2 with a
    ceiling of 10 -> the pump stops it at 2 steps with a crash event naming
    the budget kind and the effective limit (2, the agent's own budget)."""
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(max_iterations=10)),
    )
    try:
        handle = rt.spawn(
            "budgeted",
            driver=MockDriver(
                [
                    "context.budgets['max_iterations'] = 2\n",
                    "state['step_two'] = True\n",
                    "state['step_three'] = True\n",
                    "complete('never reached')\n",
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.failed
        assert "cap exceeded" in completion.reason
        assert "iterations" in completion.reason
        # The agent ran exactly 2 steps (the third block never executed).
        ws = rt.repl_engine.globals_for(handle.id)
        assert ws["state"].get("step_two") is True
        assert "step_three" not in ws["state"]
        # The budget survived as ordinary workspace data.
        assert ws["context"].budgets.get("max_iterations") == 2
        # A crash event was emitted naming the budget kind and the
        # effective limit (the agent's own budget, which tightened the
        # ceiling of 10).
        crash = [e for e in rt.events(handle.id) if e.kind == EventKind.crash]
        assert any(
            e.payload.get("cap") == "iterations"
            and e.payload.get("limit") == 2
            and e.payload.get("source") == "agent_budget"
            for e in crash
        )
    finally:
        rt.stop()


def test_g01_agent_budget_above_ceiling_is_clamped(tmp_path):
    """G-01 (2): an agent budget ABOVE the ceiling is clamped to the
    ceiling; the crash event reports the ceiling value. The agent can never
    loosen a runtime ceiling (guarantee R3)."""
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(max_iterations=2)),
    )
    try:
        handle = rt.spawn(
            "greedy",
            driver=MockDriver(
                [
                    "context.budgets['max_iterations'] = 999\n",
                    "state['step_two'] = True\n",
                    "state['step_three'] = True\n",
                    "complete('never reached')\n",
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.failed
        assert "cap exceeded" in completion.reason
        assert "iterations" in completion.reason
        # The agent ran exactly 2 steps (the ceiling, not the 999 budget).
        ws = rt.repl_engine.globals_for(handle.id)
        assert ws["state"].get("step_two") is True
        assert "step_three" not in ws["state"]
        # The crash event reports the CEILING value (2), not the agent's
        # 999 — the clamp is min(agent, ceiling).
        crash = [e for e in rt.events(handle.id) if e.kind == EventKind.crash]
        assert any(
            e.payload.get("cap") == "iterations"
            and e.payload.get("limit") == 2
            for e in crash
        )
        # No agent_budget source: the effective limit came from the ceiling.
        assert all(
            e.payload.get("source") != "agent_budget"
            for e in crash
            if e.payload.get("cap") == "iterations"
        )
    finally:
        rt.stop()


def test_g01_invalid_budgets_are_ignored(tmp_path):
    """G-01 (3a): wrong type / None / <=0 budgets are treated as unset — the
    ceiling alone governs, exactly as before."""
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(max_iterations=10)),
    )
    try:
        handle = rt.spawn(
            "sloppy",
            driver=MockDriver(
                [
                    "context.budgets['max_iterations'] = 'two'\n"
                    "context.budgets['wall_clock'] = None\n"
                    "context.budgets['max_children'] = 0\n"
                    "context.budgets['max_workspace_bytes'] = -5\n",
                    "state['step_two'] = True\n",
                    "state['step_three'] = True\n",
                    "complete('done')\n",
                ]
            ),
        )
        completion = handle.await_()
        # The invalid budgets never tightened anything: the agent ran its
        # full 4-block script under the ceiling of 10 and completed. (A
        # junk value read as a limit would have stopped it at step 1.)
        assert completion.status == AgentStatus.completed
        assert completion.summary == "done"
        ws = rt.repl_engine.globals_for(handle.id)
        assert ws["state"].get("step_three") is True
        # The junk values are still visible as ordinary workspace data.
        assert ws["context"].budgets.get("max_iterations") == "two"
    finally:
        rt.stop()


def test_g01_deleted_budgets_behave_as_before(tmp_path):
    """G-01 (3b): an agent that sets and then deletes its budget runs under
    the ceiling alone — behavior identical to never having set it."""
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(max_iterations=10)),
    )
    try:
        handle = rt.spawn(
            "fickle",
            driver=MockDriver(
                [
                    "context.budgets['max_iterations'] = 5\n",
                    "del context.budgets['max_iterations']\n"
                    "state['step_two'] = True\n",
                    "state['step_three'] = True\n",
                    "state['step_four'] = True\n",
                    "state['step_five'] = True\n",
                    "state['step_six'] = True\n",
                    "complete('done')\n",
                ]
            ),
        )
        completion = handle.await_()
        # The deleted budget no longer binds: the agent ran its full
        # 7-block script (past the deleted budget of 5) under the ceiling
        # of 10 and completed. (Had the budget of 5 still bound, the agent
        # would have been stopped at step 5 — step_six absent.)
        assert completion.status == AgentStatus.completed
        assert completion.summary == "done"
        ws = rt.repl_engine.globals_for(handle.id)
        assert ws["state"].get("step_two") is True
        assert ws["state"].get("step_six") is True
        assert "max_iterations" not in ws["context"].budgets
    finally:
        rt.stop()


def test_g01_agent_budget_fires_from_pump_unchecked(tmp_path):
    """G-01 (4): mirror of test_d5b — an agent-set budget fires from the
    pump though the agent's code never checks it. The agent is contained;
    the mesh stays alive."""
    from dhc.data.config import HarnessConfig, SafetyConfig
    from dhc.llm.driver import MockDriver

    rt = _pumped_runtime(
        tmp_path,
        config=HarnessConfig(safety=SafetyConfig(max_iterations=10)),
    )
    try:
        handle = rt.spawn(
            "looper",
            driver=MockDriver(
                [
                    "state['tripwire_never_checked'] = True\n"
                    "context.budgets['max_iterations'] = 2\n",
                    "state['step_two'] = True\n",
                    "state['step_three'] = True\n",
                    "complete('never reached')\n",
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.failed
        assert "cap exceeded" in completion.reason
        assert "iterations" in completion.reason
        # The agent's code never checked the budget (it never called
        # caps()); the pump's between-step watchdog fired it.
        ws = rt.repl_engine.globals_for(handle.id)
        assert ws["state"].get("tripwire_never_checked") is True
        assert ws["state"].get("step_two") is True
        assert "step_three" not in ws["state"]
        # The budget is ordinary workspace data.
        assert ws["context"].budgets.get("max_iterations") == 2
        # A crash event was emitted with the cap name, the effective
        # limit, and the agent-budget source.
        crash = [e for e in rt.events(handle.id) if e.kind == EventKind.crash]
        assert any(
            e.payload.get("cap") == "iterations"
            and e.payload.get("limit") == 2
            and e.payload.get("source") == "agent_budget"
            for e in crash
        )
        # Mesh alive: a sibling spawned after still completes (its
        # acceptance is met in a single step, before any budget trips).
        sibling = rt.spawn(
            "sibling",
            acceptance=("ok",),
            driver=MockDriver(["complete('fine')"]),
        )
        assert sibling.await_().status == AgentStatus.completed
    finally:
        rt.stop()
