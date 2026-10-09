"""Tests for the directed-message primitive: Runtime.send / Agent.send.

Decision 0015: direct agent-to-agent messaging is a FRAMEWORK primitive —
a receiver-addressed ``message_sent`` event delivered on the recipient's own
event stream, so the message rides the existing delivery pipeline (digest,
recent context, ``events`` tool) with no channel tooling installed. Channel
policies (rooms, escalation, operator questions, the inbox view) are
tooling composed over this primitive.

These tests run against BARE runtimes (no tooling) — that is the point.
"""

import threading

import pytest

from dhc.framework.agent import Agent
from dhc.framework.runtime import Runtime
from dhc.data.models import EventKind
from dhc.errors import ChannelError


def _register(runtime, agent_id, parent_id=None):
    agent = Agent(id=agent_id, requirement="r", parent_id=parent_id, runtime=runtime)
    runtime._agents[agent_id] = agent
    # Register the stop flag too so rt.stop() can sweep the agent cleanly
    # (spawn() does this; manual registration must match).
    runtime._stop_flags.setdefault(agent_id, threading.Event())
    return agent


def test_send_returns_receiver_addressed_event():
    rt = Runtime()
    rt.start()
    _register(rt, "a1")
    _register(rt, "a2")
    event = rt.send("a1", "a2", "hello")
    assert event.kind == EventKind.message_sent
    assert event.agent_id == "a2"
    assert event.payload["sender_id"] == "a1"
    assert event.payload["body"] == "hello"
    assert event.payload["message_id"]


def test_send_delivers_on_recipient_stream_not_sender():
    rt = Runtime()
    rt.start()
    _register(rt, "a1")
    _register(rt, "a2")
    rt.send("a1", "a2", "hello")

    recipient_events = rt.events("a2")
    assert [e.kind for e in recipient_events] == [EventKind.message_sent]
    assert recipient_events[0].payload["body"] == "hello"
    # The sender's own stream does NOT carry the message — delivery is the
    # recipient's, observability of the send is the operator's (global log).
    assert rt.events("a1") == []


def test_send_is_fifo_per_recipient():
    rt = Runtime()
    rt.start()
    _register(rt, "a1")
    _register(rt, "a2")
    rt.send("a1", "a2", "first")
    rt.send("a1", "a2", "second")
    bodies = [e.payload["body"] for e in rt.events("a2")]
    assert bodies == ["first", "second"]


def test_send_unknown_recipient_raises():
    rt = Runtime()
    rt.start()
    _register(rt, "a1")
    with pytest.raises(ChannelError):
        rt.send("a1", "ghost", "hello")


def test_send_sender_is_freeform_identity():
    """The operator (not an agent) may send; only the recipient is validated."""
    rt = Runtime()
    rt.start()
    _register(rt, "a2")
    event = rt.send("operator", "a2", "steer: do X")
    assert event.payload["sender_id"] == "operator"
    assert event.agent_id == "a2"


def test_send_message_ids_unique():
    rt = Runtime()
    rt.start()
    _register(rt, "a1")
    _register(rt, "a2")
    ids = {rt.send("a1", "a2", "m").payload["message_id"] for _ in range(5)}
    assert len(ids) == 5


def test_agent_send_delegates_to_runtime():
    rt = Runtime()
    rt.start()
    a1 = _register(rt, "a1")
    _register(rt, "a2")
    event = a1.send("a2", "via agent surface")
    assert event.kind == EventKind.message_sent
    assert event.agent_id == "a2"
    assert [e.payload["body"] for e in rt.events("a2")] == ["via agent surface"]


def test_send_in_bare_base_namespace():
    """``send`` is a core namespace name (an action, like spawn/complete) —
    present in a bare runtime with no tooling registered (decision 0015)."""
    rt = Runtime()
    agent = Agent(id="a1", requirement="r", runtime=rt)
    ns = rt._build_namespace(agent)
    assert "send" in ns
    assert callable(ns["send"])


def test_send_unattached_agent_raises():
    agent = Agent(id="a1", requirement="r", runtime=None)
    with pytest.raises(RuntimeError):
        agent.send("a2", "hello")


def test_wired_send_reaches_events_tool_and_view(tmp_path):
    """On a fully-wired stack, a direct message reaches the recipient's
    ``events`` tool (the agent-facing consume-once read) and the tooling
    Messenger view — the primitive and the policy agree because they read
    the same stream."""
    from dhc import build_runtime

    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    try:
        _register(rt, "a1")
        _register(rt, "a2")

        rt.get("a1").send("a2", "wired hello")

        seen = rt.tool_events("a2")
        assert [e.kind for e in seen] == [EventKind.message_sent]
        assert seen[0].payload["body"] == "wired hello"
        assert rt.messenger.unread_count("a2") == 1
        assert [m.body for m in rt.messenger.inbox("a2")] == ["wired hello"]
        # Boundary record: one send, one "messaged" record (INFO-049).
        assert [r["kind"] for r in rt.boundary_log.read()] == ["messaged"]
    finally:
        rt.stop()
