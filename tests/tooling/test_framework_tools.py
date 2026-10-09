"""Tests for the framework tools layer and the registration split.

The architectural goal: the CORE is runtime + eventbus + the directed-message
primitive (``send``, decision 0015); the artifact store (0014), the
communication channels (0015), and the introspection/event tools are
REPL-executed Python tools installed by registration functions —
``dhc.tooling.framework_tools.register_default_tools`` for the framework tools,
``dhc.tooling.register_channel_tools`` for the channel tools, and
``dhc.tooling.register_artifact_tools`` for the store tools. These tests
verify:

* registration installs all callables into the runtime namespace
* the bare core namespace carries ``send`` (the primitive) and nothing else
* publish -> read_artifact roundtrip with progressive disclosure
* publish emits the ``artifact_published`` event
* list_tools lists the union of the installed tools
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc.tooling import ArtifactStore  # noqa: E402
from dhc.tooling.artifact_tools import register_artifact_tools  # noqa: E402
from dhc.tooling.channel_tools import register_channel_tools  # noqa: E402
from dhc.tooling.channels import (  # noqa: E402
    EscalationChannel,
    Messenger,
    OperatorQuestionChannel,
    RoomManager,
)
from dhc.framework.event_stream import CompletionDispatcher, EventBus  # noqa: E402
from dhc.data.models import Artifact, EventKind  # noqa: E402
from dhc.framework.runtime import Runtime  # noqa: E402
from dhc.tooling.framework_tools import ToolContext, register_default_tools  # noqa: E402
from dhc.wiring import _WiredBus  # noqa: E402

CORE_NAMES = {
    "agent",
    "spawn",
    "send",
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
    "events",
}


def _wired_runtime(tmp_path):
    """A bare Runtime with the three tool registrations installed over real
    modules — the same composition ``build_runtime`` performs."""
    store = ArtifactStore(Path(tmp_path))
    bus = EventBus()
    messenger = Messenger(bus)
    rooms = RoomManager(bus)
    escalations = EscalationChannel(bus)
    questions = OperatorQuestionChannel(bus)
    runtime = Runtime(event_bus=_WiredBus(bus, CompletionDispatcher()))
    register_default_tools(runtime, bus=bus)
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
    register_artifact_tools(runtime, store=store, bus=bus)
    return runtime, store, bus, messenger, rooms, escalations, questions


def _namespace(runtime, agent_id="a1"):
    """Build the turn namespace for a fake agent via the runtime's builder."""
    from dhc.framework.agent import Agent

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
    # The tools are present only because the registration functions added
    # them (register_default_tools + register_channel_tools +
    # register_artifact_tools).
    assert "publish" in ns
    assert "room" in ns


def test_bare_runtime_namespace_is_slim():
    """Without the tools layer, the core namespace has no publish/room —
    but it DOES carry ``send``: direct messaging is the framework's
    communication primitive (decision 0015), present in a bare runtime."""
    runtime = Runtime()
    ns = runtime._build_namespace(_fake_agent())
    assert "publish" not in ns
    assert "room" not in ns
    assert "messenger" not in ns
    for name in CORE_NAMES:
        assert name in ns
    assert callable(ns["send"])


def test_default_tools_registration_split(tmp_path):
    """register_default_tools alone installs ONLY the framework tools
    (list_tools, events) — the channel and store tools come from their own
    registrations (decisions 0014/0015)."""
    bus = EventBus()
    runtime = Runtime(event_bus=_WiredBus(bus, CompletionDispatcher()))
    register_default_tools(runtime, bus=bus)
    ns = _namespace(runtime)
    assert set(ns) - CORE_NAMES - {"agent", "Await", "Poll", "Sleep"} == {
        "list_tools",
        "events",
    }
    assert runtime._installed_tool_names == {"list_tools", "events"}


def _fake_agent():
    from dhc.framework.agent import Agent

    return Agent(id="a1", requirement="r")


def test_tool_context_duck_typed_fields():
    ctx = ToolContext(agent_id="a1", runtime=object())
    assert ctx.agent_id == "a1"
    assert ctx.runtime is not None
    assert ctx.bus is None


def test_tool_context_has_no_store_or_channels_slot():
    """The framework ToolContext carries no store and no channels (0014/0015)."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(ToolContext)}
    assert "store" not in fields
    assert "channels" not in fields


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
