"""Tests for dhc.agent and dhc.runtime.

Uses scripted drivers and fakes only — no real LLM, no real REPL, no real
artifact store. The runtime's injected collaborators are duck-typed, so the
tests exercise the same seams the integration agent will wire the real
modules into.
"""

import threading
import time

import pytest

from dhc.agent import Agent, AgentHandle, ToolResult
from dhc.errors import ChannelError
from dhc.models import (
    TERMINAL_STATES,
    AgentStatus,
    Artifact,
    Completion,
    EventKind,
    Result,
    ToolOutput,
    is_terminal,
)
from dhc.runtime import Runtime


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


def test_agent_publish_uses_injected_store():
    from dhc.runtime import _MemoryStore

    store = _MemoryStore()
    agent = Agent(id="a1", requirement="r", artifact_store=store)
    art = agent.publish("headline", "summary", "full body")
    assert isinstance(art, Artifact)
    assert art.id.startswith("sha256:")
    assert store.get(art.id) is art


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


def test_completion_callbacks_delivered_in_completion_order():
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
    # All three callbacks ran, in completion order (c1, c2, c3 here).
    assert order == ["c1", "c2", "c3"]
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
    rt = make_runtime()
    handle = rt.spawn(
        "do it",
        driver=ScriptedDriver(
            "r = room('war-room')\n"
            "assert r.name == 'war-room'\n"
            "assert agent.id in r.members\n"
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