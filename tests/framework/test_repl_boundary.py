"""The framework↔REPL boundary enforcement suite.

Pins the hard interface contract on everything that crosses from the
framework into agent-authored code:

* ``agent`` is the :class:`~dhc.framework.agent.WorkspaceAgent` facade —
  never the raw :class:`~dhc.framework.agent.Agent` — and its public
  surface is exactly the declared
  :data:`~dhc.framework.agent.AGENT_SURFACE`.
* every core namespace action callable is facade-bound — no raw framework
  machinery (``Runtime``, ``ReplEngine``, ``EventBus``/``EventStream``,
  ``CompletionDispatcher``, raw ``Agent``) appears as a namespace value.
* ``spawn`` returns an :class:`~dhc.framework.agent.AgentHandle` with no
  unwrap (``get``).
* events cross as deep-copy snapshots — post-emission ``payload`` mutation
  stays private to the reader.
* the fabrication ``context`` is ordinary workspace data (no public
  ``runtime``/``engine``, no agent object in ``as_dict()``), and ``room()``
  returns a snapshot of the shared room.
* settlement is gated by the :class:`~dhc.models.CompletionLog` FIRST — a
  forged terminal ``_status`` (reachable only by reaching around the
  declared surface) can never suppress the real completion.

Deliberate crossings, documented and NOT blocked here: ``bash`` and
import rights (CodeAct — blocks run arbitrary Python), ``state["_driver"]``
(the brain-swap seam), ``MockDriver``/``driver_from_settings`` in the
namespace (spawn-time driver selection), and the driver seam itself
(INFO-051 — the driver is runtime machinery and receives the raw Agent).
This suite pins the *declared* surface; it cannot and does not try to
prevent reach-around introspection from arbitrary Python.
"""

import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc.data.models import AgentStatus, EventKind, Result  # noqa: E402
from dhc.framework.agent import (  # noqa: E402
    AGENT_SURFACE,
    Agent,
    AgentHandle,
    AgentSurface,
    WorkspaceAgent,
)
from dhc.framework.runtime import Runtime  # noqa: E402
from dhc.llm.driver import MockDriver  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _bare() -> Runtime:
    rt = Runtime()
    rt.start()
    return rt


def _wired(tmp_path) -> Runtime:
    """A fully-wired runtime (ReplEngine + fabrication kit) over tmp_path."""
    from dhc.data.config import Settings
    from dhc.wiring import build_runtime

    settings = Settings(workspace_root=tmp_path, artifact_root=tmp_path)
    rt = build_runtime(mock=True, artifact_root=tmp_path, settings=settings)
    rt.start()
    return rt


# --------------------------------------------------------------------------- #
# The agent surface
# --------------------------------------------------------------------------- #


def test_namespace_agent_is_facade_not_raw_agent():
    """Blocks see the WorkspaceAgent facade; action callables are its bound
    methods (``__self__`` is the facade), so the raw agent is not reachable
    through the declared surface."""
    rt = _bare()
    try:
        handle = rt.spawn("t", driver=MockDriver.single("complete('done')"))
        agent = rt.get(handle.id)
        ns = rt._build_namespace(agent)
        assert isinstance(ns["agent"], WorkspaceAgent)
        assert not isinstance(ns["agent"], Agent)
        assert ns["agent"].id == agent.id
        for name in (
            "spawn",
            "send",
            "complete",
            "fail",
            "cancel",
            "status",
            "result",
            "tool",
            "await_",
            "poll",
            "children_of",
        ):
            assert ns[name].__self__ is ns["agent"], name
    finally:
        rt.stop()


def test_workspace_agent_public_surface_is_declared():
    """``dir(agent)`` public names == AGENT_SURFACE, and the dangerous raw
    members (runtime ref, settlement state, usage recorder) are absent."""
    rt = _bare()
    try:
        handle = rt.spawn("t", driver=MockDriver.single("complete('done')"))
        surface = rt._build_namespace(rt.get(handle.id))["agent"]
        public = {name for name in dir(surface) if not name.startswith("_")}
        assert public == set(AGENT_SURFACE)
        for absent in (
            "_runtime",
            "_status",
            "_result",
            "_last_result",
            "record_usage",
        ):
            assert not hasattr(surface, absent), absent
        # children is a read-only copy, not the shared mutable list.
        assert isinstance(surface.children, tuple)
        assert surface.children == tuple(rt.get(handle.id).children)
        # The facade satisfies the declared protocol.
        assert isinstance(surface, AgentSurface)
    finally:
        rt.stop()


def test_blocks_see_the_facade_end_to_end(tmp_path):
    """A block that runs in a real (wired, pumped) workspace sees the
    facade as ``agent`` and settles normally through it."""
    rt = _wired(tmp_path)
    try:
        handle = rt.spawn(
            "t",
            driver=MockDriver.single(
                "seen = type(agent).__name__\ncomplete('done')"
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        ws = rt.repl_engine.globals_for(handle.id)
        assert ws["seen"] == "WorkspaceAgent"
        assert isinstance(ws["agent"], WorkspaceAgent)
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# Handle discipline
# --------------------------------------------------------------------------- #


def test_spawn_returns_handle_and_handles_do_not_unwrap():
    """Agent.spawn returns the AgentHandle (the join surface); the handle
    has no ``get()`` unwrap to the raw child."""
    rt = _bare()
    try:
        parent = rt.spawn("parent", driver=MockDriver([]))
        agent = rt.get(parent.id)
        child = agent.spawn(
            "child task", driver=MockDriver.single("complete('child done')")
        )
        assert isinstance(child, AgentHandle)
        assert not hasattr(child, "get")
        assert rt.get(child.id).id == child.id
        completion = child.await_()
        assert completion.status == AgentStatus.completed
        assert child.id in agent.children
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# Namespace machinery scan (wired runtime)
# --------------------------------------------------------------------------- #


def test_wired_namespace_holds_no_framework_machinery(tmp_path):
    """No fully-wired namespace value (or its bound ``__self__``) is a raw
    framework machinery object: Runtime, raw Agent, ReplEngine,
    EventBus/EventStream, or CompletionDispatcher."""
    from dhc.framework.event_stream import (
        CompletionDispatcher,
        EventBus,
        EventStream,
    )
    from dhc.framework.repl import ReplEngine

    rt = _wired(tmp_path)
    try:
        handle = rt.spawn("t", driver=MockDriver.single("complete('done')"))
        handle.await_()
        ns = rt._build_namespace(rt.get(handle.id))
        assert ns, "the wired namespace must not be empty"
        banned = (Runtime, Agent, ReplEngine, EventBus, EventStream, CompletionDispatcher)
        for name, value in ns.items():
            holders = [value]
            bound_self = getattr(value, "__self__", None)
            if bound_self is not None:
                holders.append(bound_self)
            for holder in holders:
                assert not isinstance(holder, banned), (name, type(holder))
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# Event crossing snapshots
# --------------------------------------------------------------------------- #


def _message_events(events):
    return [e for e in events if e.kind == EventKind.message_sent]


def test_events_crossing_returns_snapshots(tmp_path):
    """Events handed to REPL-side readers (``tool_events``/``events``) are
    deep copies: mutating the returned payload is a private edit that
    neither the stream's pending events nor other readers ever see."""
    rt = _wired(tmp_path)
    try:
        sender = rt.spawn("s", driver=MockDriver.single("complete('s')"))
        receiver = rt.spawn("r", driver=MockDriver.single("complete('r')"))
        # Settle first: the receiver's own observe() consumes via the
        # events cursor, so the message must land after it is done.
        sender.await_()
        receiver.await_()
        rt.send(sender.id, receiver.id, "hello")

        received = _message_events(rt.tool_events(receiver.id))
        assert len(received) == 1
        # Forge the crossing snapshot...
        received[0].payload["body"] = "forged"

        # ...the stream's pending events keep the emitted values...
        pending = _message_events(rt.bus.stream_for(receiver.id).peek())
        assert pending[0].payload["body"] == "hello"

        # ...and an independent reader (the observe cursor) sees them too.
        again = _message_events(rt.events(receiver.id))
        assert again[0].payload["body"] == "hello"
        assert again[0] is not pending[0]
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# The fabrication context crossing
# --------------------------------------------------------------------------- #


def test_fabrication_context_is_pure_workspace_data(tmp_path):
    """The workspace ``context`` carries no public runtime/engine and its
    dict view carries no agent object. The brain-swap seam
    (``state["_driver"]``) stays — that crossing is deliberate."""
    rt = _wired(tmp_path)
    try:
        handle = rt.spawn("t", driver=MockDriver.single("complete('done')"))
        handle.await_()
        ws = rt.repl_engine.globals_for(handle.id)
        ctx = ws["context"]
        assert ctx.agent_id == handle.id
        assert not hasattr(ctx, "runtime")
        assert not hasattr(ctx, "engine")
        d = ctx.as_dict()
        assert "agent" not in d
        assert d["agent_id"] == handle.id
        # Deliberate crossing, by design: the brain-swap seam.
        assert "_driver" in ws["state"]
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# Channel tool snapshots
# --------------------------------------------------------------------------- #


def test_room_tool_returns_a_snapshot(tmp_path):
    """``room(name)`` joins for real but returns a snapshot: mutating the
    returned Room bypasses nothing (membership, history, the posting
    gate), and a fresh read does not see the mutation."""
    rt = _wired(tmp_path)
    try:
        handle = rt.spawn("t", driver=MockDriver.single("complete('done')"))
        handle.await_()
        agent = rt.get(handle.id)
        ns = rt._build_namespace(agent)

        room = ns["room"]("war-room")
        assert agent.id in room.member_ids

        # The tool value is a private copy, not the shared room.
        room.member_ids.append("forged")
        fresh = ns["room"]("war-room")
        assert "forged" not in fresh.member_ids
        assert fresh.messages == []

        # Posting through the gate is still the only way traffic appears.
        message = ns["post"]("war-room", "through the gate")
        assert message.body == "through the gate"
        after = ns["room"]("war-room")
        assert [m.body for m in after.messages] == ["through the gate"]
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# Settlement gate: the log is the source of truth
# --------------------------------------------------------------------------- #


def test_settlement_log_is_source_of_truth_over_forged_status():
    """A forged terminal ``_status`` (simulating a reach-around past the
    facade) cannot suppress the real settlement: the CompletionLog gates
    first, so the real completion still lands and the forged state is
    corrected."""
    rt = _bare()
    entered = threading.Event()
    gate = threading.Event()

    def gated_driver(agent):
        # Park the worker so the test controls the settlement order.
        entered.set()
        gate.wait(timeout=10)
        return None

    try:
        handle = rt.spawn("t", driver=gated_driver)
        assert entered.wait(timeout=10)
        agent = rt.get(handle.id)

        # The reach-around forgery: terminal status, no log entry.
        agent._status = AgentStatus.completed
        agent._result = Result(done=True, ok=True, value="forged")

        # The real settle path still lands (the log, not _status, decides).
        rt._settle(handle.id, AgentStatus.failed, reason="the real outcome")
        completion = rt.await_(handle.id)
        assert completion.status == AgentStatus.failed
        assert completion.reason == "the real outcome"
        assert handle.id in rt._completions
        assert rt.get(handle.id)._status == AgentStatus.failed

        # Releasing the worker: its own settle attempt is rejected by the
        # log (at-most-once), never a double settlement.
        gate.set()
    finally:
        gate.set()
        rt.stop()


def test_double_settle_still_rejected_by_the_log():
    """The reorder keeps at-most-once: a second real settlement for the
    same agent is rejected and does not dispatch twice."""
    rt = _bare()
    try:
        handle = rt.spawn(
            "t", driver=MockDriver.single("complete('done')")
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        # A late second settlement attempt is a contained no-op.
        rt._settle(handle.id, AgentStatus.failed, reason="late")
        assert rt.completion_log().get(handle.id).status == AgentStatus.completed
        assert rt.await_(handle.id) is completion
    finally:
        rt.stop()
