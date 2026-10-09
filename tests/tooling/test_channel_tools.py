"""Tests for dhc.tooling.channel_tools: the channel policies as REPL tools.

Decision 0015: the channel tools (room, messenger, escalate, ask_operator,
post, channel_read) are operator tooling installed by
``register_channel_tools`` — policies over the core directed-message
primitive (``Runtime.send``). These tests verify the registration mechanics
and each tool through a runtime wired like ``build_runtime`` does.
"""

import pytest

from dhc.tooling.channels import (
    EscalationChannel,
    Messenger,
    OperatorQuestionChannel,
    RoomManager,
)
from dhc.tooling.channel_tools import register_channel_tools
from dhc.framework.agent import Agent
from dhc.framework.event_stream import CompletionDispatcher, EventBus
from dhc.framework.runtime import Runtime
from dhc.data.models import EventKind
from dhc.wiring import _WiredBus


def _wired(tmp_path=None):
    """A runtime with the channel tools installed (mirrors build_runtime)."""
    bus = EventBus()
    messenger = Messenger(bus)
    rooms = RoomManager(bus)
    escalations = EscalationChannel(bus)
    questions = OperatorQuestionChannel(bus)
    runtime = Runtime(event_bus=_WiredBus(bus, CompletionDispatcher()))
    register_channel_tools(
        runtime,
        bus=bus,
        channels={
            "messenger": messenger,
            "rooms": rooms,
            "escalations": escalations,
            "questions": questions,
        },
    )
    return runtime, bus, messenger, rooms, escalations, questions


def _namespace(runtime, agent_id="a1"):
    agent = Agent(id=agent_id, requirement="r")
    return runtime._build_namespace(agent)


def _register(runtime, agent_id, parent_id=None):
    agent = Agent(id=agent_id, requirement="r", parent_id=parent_id)
    runtime._agents[agent_id] = agent
    return agent


def test_channel_tools_installed_with_registration():
    runtime, *_ = _wired()
    ns = _namespace(runtime)
    for name in ("room", "messenger", "escalate", "ask_operator", "post", "channel_read"):
        assert name in ns, f"tool {name!r} not installed"
    # The messenger is a per-agent facade object with methods.
    assert hasattr(ns["messenger"], "send")
    assert hasattr(ns["messenger"], "inbox")
    assert hasattr(ns["messenger"], "unread_count")


def test_channel_registration_advertises_names():
    runtime, *_ = _wired()
    assert {"room", "messenger", "escalate", "ask_operator", "post", "channel_read"} <= set(
        runtime._installed_tool_names
    )


def test_bare_runtime_has_no_channel_tools():
    runtime = Runtime()
    ns = runtime._build_namespace(Agent(id="a1", requirement="r"))
    for name in ("room", "messenger", "escalate", "ask_operator", "post", "channel_read"):
        assert name not in ns
    # The core send primitive IS present (decision 0015).
    assert "send" in ns


def test_unwired_channel_tool_raises():
    runtime = Runtime()
    register_channel_tools(runtime)  # no channels wired
    ns = _namespace(runtime)
    with pytest.raises(RuntimeError):
        ns["room"]("war-room")


def test_messenger_facade_send_delivers_via_core_primitive():
    """The facade's send delegates to Runtime.send: the message lands on the
    RECIPIENT's stream (receiver-addressed), and the view tracks it."""
    runtime, bus, messenger, *_ = _wired()
    _register(runtime, "a1")
    _register(runtime, "a2")
    ns = _namespace(runtime, agent_id="a1")

    sent = ns["messenger"].send("a2", "hello")
    assert sent.body == "hello"
    assert sent.recipient_id == "a2"

    # Receiver-addressed delivery on the recipient's stream (core).
    events = bus.stream_for("a2").drain()
    assert [e.kind for e in events] == [EventKind.message_sent]
    assert events[0].agent_id == "a2"
    assert events[0].payload["sender_id"] == "a1"
    assert events[0].payload["body"] == "hello"

    # The view's read-state sugar (tooling).
    assert len(messenger.inbox("a2")) == 1
    assert messenger.unread_count("a2") == 1
    assert ns["messenger"].inbox() == []
    assert ns["messenger"].unread_count() == 0


def test_messenger_facade_unknown_recipient_raises():
    runtime, *_ = _wired()
    _register(runtime, "a1")
    ns = _namespace(runtime, agent_id="a1")
    from dhc.errors import ChannelError

    with pytest.raises(ChannelError):
        ns["messenger"].send("ghost", "hello")


def test_room_and_post_and_channel_read():
    runtime, bus, messenger, rooms, *_ = _wired()
    _register(runtime, "a1")
    ns = _namespace(runtime, agent_id="a1")
    room = ns["room"]("war-room")
    assert room.name == "war-room"
    assert "a1" in room.member_ids
    msg = ns["post"]("war-room", "hello room")
    assert msg.body == "hello room"
    assert ns["channel_read"]("war-room") == [msg]


def test_escalate_tool_resolves_parent():
    runtime, bus, messenger, rooms, escalations, questions = _wired()
    _register(runtime, "parent")
    _register(runtime, "a1", parent_id="parent")
    agent = runtime._agents["a1"]
    ns = runtime._build_namespace(agent)
    event = ns["escalate"]("requirement-x", "unreachable")
    assert event.kind == EventKind.escalation
    assert event.agent_id == "parent"
    assert event.payload["requirement"] == "requirement-x"
    assert event.payload["reason"] == "unreachable"
    assert escalations.pending_for("parent")


def test_ask_operator_tool():
    runtime, *_, questions = _wired()
    _register(runtime, "a1")
    ns = _namespace(runtime, agent_id="a1")
    event = ns["ask_operator"]("which provider?")
    assert event.kind == EventKind.operator_question
    assert event.agent_id == "a1"
    assert questions.pending_questions()
