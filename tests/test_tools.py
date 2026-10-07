"""Tests for the tools layer: artifact store and channels as REPL tools.

The architectural goal: the CORE is only runtime + eventbus; the artifact
store and communication channels are REPL-executed Python tools installed by
:func:`dhc.tools.register_default_tools`. These tests verify:

* registration installs all callables into the runtime namespace
* publish -> read_artifact roundtrip with progressive disclosure
* publish emits the ``artifact_published`` event
* room / messenger / escalate / ask_operator work through the tools layer
* list_tools lists the installed tools
* the core namespace has no publish/room (they come from tools)
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc.artifact_store import ArtifactStore  # noqa: E402
from dhc.communication import (  # noqa: E402
    EscalationChannel,
    Messenger,
    OperatorQuestionChannel,
    RoomManager,
)
from dhc.event_stream import EventBus  # noqa: E402
from dhc.models import Artifact, EventKind  # noqa: E402
from dhc.runtime import Runtime  # noqa: E402
from dhc.tools import ToolContext, register_default_tools  # noqa: E402

CORE_NAMES = {
    "agent",
    "spawn",
    "complete",
    "fail",
    "cancel",
    "status",
    "result",
    "tool",
    "bash",
    "await_",
    "poll",
    "children_of",
}

TOOL_NAMES = {
    "publish",
    "read_artifact",
    "archive",
    "list_artifacts",
    "room",
    "messenger",
    "escalate",
    "ask_operator",
    "post",
    "channel_read",
    "list_tools",
}


class _FakeBus:
    """A minimal duck-typed bus recording published events."""

    def __init__(self) -> None:
        self.events = []

    def publish(self, event) -> None:
        self.events.append(event)


def _wired_runtime(tmp_path):
    """A bare Runtime with the tools layer installed over real modules."""
    store = ArtifactStore(Path(tmp_path))
    bus = EventBus()
    messenger = Messenger(bus, registry={"a1", "a2"})
    rooms = RoomManager(bus)
    escalations = EscalationChannel(bus)
    questions = OperatorQuestionChannel(bus)
    runtime = Runtime(artifact_store=store, event_bus=bus)
    register_default_tools(
        runtime,
        store=store,
        bus=bus,
        channels={
            "messenger": lambda agent_id: _BoundMessenger(messenger, agent_id),
            "rooms": rooms,
            "escalations": escalations,
            "questions": questions,
        },
    )
    return runtime, store, bus, messenger, rooms, escalations, questions


class _BoundMessenger:
    """Per-agent facade over the shared Messenger (mirrors wiring.py)."""

    def __init__(self, messenger, agent_id):
        self._messenger = messenger
        self._agent_id = agent_id

    def send(self, recipient_id, body):
        return self._messenger.send(self._agent_id, recipient_id, body)

    def inbox(self):
        return self._messenger.inbox(self._agent_id)

    def read(self, message_id):
        return self._messenger.read(self._agent_id, message_id)

    def unread_count(self):
        return self._messenger.unread_count(self._agent_id)


def _namespace(runtime, agent_id="a1"):
    """Build the turn namespace for a fake agent via the runtime's builder."""
    from dhc.agent import Agent

    agent = Agent(id=agent_id, requirement="r")
    return runtime._build_namespace(agent)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #


def test_register_default_tools_installs_all_callables(tmp_path):
    runtime, *_ = _wired_runtime(tmp_path)
    ns = _namespace(runtime)
    for name in TOOL_NAMES:
        assert name in ns, f"tool {name!r} not installed"
        if name == "messenger":
            # The messenger is a per-agent facade object with methods.
            assert hasattr(ns[name], "send")
            assert hasattr(ns[name], "inbox")
            assert hasattr(ns[name], "unread_count")
        else:
            assert callable(ns[name]), f"tool {name!r} is not callable"


def test_core_namespace_has_no_publish_or_room(tmp_path):
    """The slim core namespace excludes the tools (they come from tools)."""
    runtime, *_ = _wired_runtime(tmp_path)
    ns = _namespace(runtime)
    for name in CORE_NAMES:
        assert name in ns, f"core name {name!r} missing"
    # The tools are present only because register_default_tools added them.
    assert "publish" in ns
    assert "room" in ns


def test_bare_runtime_namespace_is_slim():
    """Without the tools layer, the core namespace has no publish/room."""
    runtime = Runtime()
    ns = runtime._build_namespace(_fake_agent())
    assert "publish" not in ns
    assert "room" not in ns
    for name in CORE_NAMES:
        assert name in ns


def _fake_agent():
    from dhc.agent import Agent

    return Agent(id="a1", requirement="r")


def test_tool_context_duck_typed_fields():
    ctx = ToolContext(agent_id="a1", runtime=object(), store=object())
    assert ctx.agent_id == "a1"
    assert ctx.runtime is not None
    assert ctx.store is not None
    assert ctx.bus is None
    assert ctx.channels == {}
    assert ctx.messenger is None
    assert ctx.rooms is None
    assert ctx.escalations is None
    assert ctx.questions is None


# --------------------------------------------------------------------------- #
# publish -> read_artifact roundtrip (progressive disclosure)
# --------------------------------------------------------------------------- #


def test_publish_read_artifact_roundtrip(tmp_path):
    runtime, store, *_ = _wired_runtime(tmp_path)
    ns = _namespace(runtime)
    art = ns["publish"]("headline here", "summary here", {"body": "full report"})
    assert isinstance(art, Artifact)
    assert art.id.startswith("sha256:")

    assert ns["read_artifact"](art.id, level="headline") == "headline here"
    assert ns["read_artifact"](art.id, level="summary") == "summary here"
    assert '"body": "full report"' in ns["read_artifact"](art.id, level="report")
    # Default level is summary.
    assert ns["read_artifact"](art.id) == "summary here"


def test_publish_emits_artifact_published_event(tmp_path):
    runtime, store, bus, *_ = _wired_runtime(tmp_path)
    ns = _namespace(runtime)
    art = ns["publish"]("h", "s", "r")
    events = bus.stream_for("a1").drain()
    kinds = [e.kind for e in events]
    assert EventKind.artifact_published in kinds
    # The event carries the artifact id by reference.
    published = [
        e for e in events if e.kind == EventKind.artifact_published
    ]
    assert published and published[0].payload["artifact_id"] == art.id


def test_list_artifacts_and_archive(tmp_path):
    runtime, store, *_ = _wired_runtime(tmp_path)
    ns = _namespace(runtime)
    art = ns["publish"]("h", "s", "r")
    assert ns["list_artifacts"]() == [art.id]
    path = ns["archive"](art.id)
    assert isinstance(path, str)
    assert Path(path).exists()


# --------------------------------------------------------------------------- #
# Channels through the tools layer
# --------------------------------------------------------------------------- #


def test_room_tool(tmp_path):
    runtime, store, bus, messenger, rooms, *_ = _wired_runtime(tmp_path)
    ns = _namespace(runtime, agent_id="a1")
    room = ns["room"]("war-room")
    assert room.name == "war-room"
    assert "a1" in room.member_ids
    msg = ns["post"]("war-room", "hello room")
    assert msg.body == "hello room"
    assert ns["channel_read"]("war-room") == [msg]


def test_messenger_tool(tmp_path):
    runtime, store, bus, messenger, *_ = _wired_runtime(tmp_path)
    ns = _namespace(runtime, agent_id="a1")
    sent = ns["messenger"].send("a2", "hello")
    assert sent.body == "hello"
    # a2's inbox has the message; a1's is empty.
    assert len(messenger.inbox("a2")) == 1
    assert messenger.unread_count("a2") == 1
    assert ns["messenger"].inbox() == []
    assert ns["messenger"].unread_count() == 0


def test_escalate_tool(tmp_path):
    runtime, store, bus, messenger, rooms, escalations, questions = _wired_runtime(
        tmp_path
    )
    # Give the agent a parent so escalation has an upstream target.
    from dhc.agent import Agent

    parent = Agent(id="parent", requirement="p")
    runtime._agents["parent"] = parent
    agent = Agent(id="a1", requirement="r", parent_id="parent")
    runtime._agents["a1"] = agent
    ns = runtime._build_namespace(agent)
    event = ns["escalate"]("requirement-x", "unreachable")
    assert event.kind == EventKind.escalation
    assert event.agent_id == "parent"
    assert event.payload["requirement"] == "requirement-x"
    assert event.payload["reason"] == "unreachable"
    assert escalations.pending_for("parent")


def test_ask_operator_tool(tmp_path):
    runtime, store, bus, messenger, rooms, escalations, questions = _wired_runtime(
        tmp_path
    )
    ns = _namespace(runtime, agent_id="a1")
    event = ns["ask_operator"]("which provider?")
    assert event.kind == EventKind.operator_question
    assert event.agent_id == "a1"
    assert questions.pending_questions()


def test_list_tools(tmp_path):
    runtime, *_ = _wired_runtime(tmp_path)
    ns = _namespace(runtime)
    tools = ns["list_tools"]()
    assert set(tools) == TOOL_NAMES


# --------------------------------------------------------------------------- #
# Wiring integration: build_runtime installs the tools
# --------------------------------------------------------------------------- #


def test_build_runtime_installs_tools(tmp_path):
    from dhc import build_runtime

    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    try:
        ns = rt._build_namespace(rt.get(rt.spawn("r").id))
        for name in TOOL_NAMES:
            assert name in ns, f"tool {name!r} not installed by build_runtime"
            if name == "messenger":
                assert hasattr(ns[name], "send")
            else:
                assert callable(ns[name])
    finally:
        rt.stop()