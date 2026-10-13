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
from dhc.llm.driver import MockDriver  # noqa: E402
from dhc.tooling.framework_tools import ToolContext, register_default_tools  # noqa: E402
from dhc.wiring import _WiredBus  # noqa: E402

CORE_NAMES = {
    "agent",
    "spawn",
    "send",
    "complete",
    "fail",
    "record_result",
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
        "ack",
        "answers",
        "gather",
    }
    assert runtime._installed_tool_names == {
        "list_tools",
        "events",
        "ack",
        "answers",
        "gather",
    }


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
    """W1.6: list_tools() reads from the surface registry — it lists
    exactly the registry's core+advanced tier (a superset of the
    historical 12 tool names: the core actions are part of the surface
    too, and the registry is the single source of truth)."""
    from dhc.framework.surface import default_registry

    runtime, *_ = _wired_runtime(tmp_path)
    ns = _namespace(runtime)
    tools = ns["list_tools"]()
    assert set(tools) == set(default_registry.list_tools())
    # The historical tool names are all still listed.
    assert TOOL_NAMES <= set(tools)
    # The core actions are listed too (they are core-tier surface).
    assert CORE_NAMES <= set(tools)


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


# --------------------------------------------------------------------------- #
# W3.2: read_artifact level aliases are official
# --------------------------------------------------------------------------- #


def test_read_artifact_full_and_raw_are_report_aliases(tmp_path):
    """W3.2: ``full`` and ``raw`` are official aliases of ``report``."""
    runtime, *_ = _wired_runtime(tmp_path)
    ns = _namespace(runtime)
    art = ns["publish"]("h", "s", {"body": "full report"})
    report = ns["read_artifact"](art.id, level="report")
    assert ns["read_artifact"](art.id, level="full") == report
    assert ns["read_artifact"](art.id, level="raw") == report
    assert '"body": "full report"' in report


def test_read_artifact_invalid_level_lists_all_five_levels(tmp_path):
    """W3.2: the ValueError names all five accepted levels."""
    runtime, *_ = _wired_runtime(tmp_path)
    ns = _namespace(runtime)
    art = ns["publish"]("h", "s", "r")
    with pytest.raises(ValueError) as excinfo:
        ns["read_artifact"](art.id, level="bogus")
    msg = str(excinfo.value)
    for level in ("headline", "summary", "report", "full", "raw"):
        assert level in msg, f"level {level!r} missing from error: {msg}"


# --------------------------------------------------------------------------- #
# W3.10 (archive half): loud failure when no path is derivable
# --------------------------------------------------------------------------- #


class _PathlessStore:
    """Duck-typed store with NO path surface (no path_for/_root/root)."""

    def __init__(self):
        self._items = {}

    def publish(self, headline, summary, report):
        art = Artifact(headline=headline, summary=summary, report=report)
        self._items[art.id] = art
        return art

    def exists(self, artifact_id):
        return artifact_id in self._items

    def get_headline(self, artifact_id):
        return self._items[artifact_id].headline

    def get_summary(self, artifact_id):
        return self._items[artifact_id].summary

    def get_report(self, artifact_id):
        return self._items[artifact_id].report

    def list_ids(self):
        return list(self._items)


def test_archive_pathless_store_raises_naming_id(tmp_path):
    """W3.10: archive() on a store with no path surface raises
    ArtifactNotFoundError naming the offending artifact id."""
    from dhc.errors import ArtifactNotFoundError

    store = _PathlessStore()
    bus = EventBus()
    runtime = Runtime(event_bus=_WiredBus(bus, CompletionDispatcher()))
    register_artifact_tools(runtime, store=store, bus=bus)
    ns = _namespace(runtime)
    art = ns["publish"]("h", "s", "r")
    with pytest.raises(ArtifactNotFoundError) as excinfo:
        ns["archive"](art.id)
    assert art.id in str(excinfo.value)


# --------------------------------------------------------------------------- #
# Wave 3: ack / answers / gather + tier moves (W3.5 + W3.6 + W3.8)
# --------------------------------------------------------------------------- #


def test_ack_end_to_end(tmp_path):
    """W3.6: child escalates -> parent acks the event id -> second ack
    raises ChannelError (already acknowledged)."""
    from dhc import build_runtime
    from dhc.errors import ChannelError

    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    try:
        parent = rt.spawn("parent", driver=MockDriver.single("complete('p')"))
        child = rt.spawn(
            "child",
            driver=MockDriver.single("complete('c')"),
            parent_id=parent.id,
        )
        pns = rt._build_namespace(rt.get(parent.id))
        cns = rt._build_namespace(rt.get(child.id))
        event = cns["escalate"]("need X", "cannot reach X")
        event_id = event.payload["event_id"]
        pns["ack"](event_id)  # closes the loop
        with pytest.raises(ChannelError):
            pns["ack"](event_id)  # already acknowledged
    finally:
        rt.stop()


def test_answers_end_to_end(tmp_path):
    """W3.6: ask_operator returns the question id -> answers(qid) polls []
    until the operator answers, then returns the answer text."""
    from dhc import build_runtime

    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    try:
        agent = rt.spawn("asker", driver=MockDriver.single("complete('a')"))
        ns = rt._build_namespace(rt.get(agent.id))
        qid = ns["ask_operator"]("which?")
        assert isinstance(qid, str) and qid
        assert ns["answers"](qid) == []  # polling: unanswered yet
        rt.questions.answer(qid, "yes")
        assert ns["answers"](qid) == ["yes"]
    finally:
        rt.stop()


def test_gather_success(tmp_path):
    """W3.8: gather joins spawned children and returns their Completions."""
    from dhc import build_runtime
    from dhc.data.models import AgentStatus, Completion

    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    try:
        parent = rt.spawn("parent", driver=MockDriver.single("complete('p')"))
        handles = [
            rt.spawn(f"child {i}", driver=MockDriver.single("complete('done')"))
            for i in range(3)
        ]
        ns = rt._build_namespace(rt.get(parent.id))
        completions = ns["gather"](handles)
        assert len(completions) == 3
        assert all(isinstance(c, Completion) for c in completions)
        assert all(c.status == AgentStatus.completed for c in completions)
        assert {c.agent_id for c in completions} == {h.id for h in handles}
    finally:
        rt.stop()


def test_gather_failure_paths(tmp_path):
    """W3.8: return_failures=False drops non-completed children;
    return_failures=True returns every completion for inspection."""
    from dhc import build_runtime
    from dhc.data.models import AgentStatus

    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    try:
        parent = rt.spawn("parent", driver=MockDriver.single("complete('p')"))
        h_fail = rt.spawn("failing", driver=MockDriver.single("fail('nope')"))
        h_ok = rt.spawn("ok", driver=MockDriver.single("complete('done')"))
        ns = rt._build_namespace(rt.get(parent.id))
        ok_only = ns["gather"]([h_fail, h_ok])
        assert len(ok_only) == 1
        assert ok_only[0].agent_id == h_ok.id
        assert ok_only[0].status == AgentStatus.completed
        all_of_them = ns["gather"]([h_fail, h_ok], return_failures=True)
        assert len(all_of_them) == 2
        by_id = {c.agent_id: c for c in all_of_them}
        assert by_id[h_fail.id].status == AgentStatus.failed
        assert by_id[h_ok.id].status == AgentStatus.completed
    finally:
        rt.stop()


def test_gather_empty(tmp_path):
    """W3.8: gather([]) is [] (no handles, no joins)."""
    from dhc import build_runtime

    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    try:
        parent = rt.spawn("parent", driver=MockDriver.single("complete('p')"))
        ns = rt._build_namespace(rt.get(parent.id))
        assert ns["gather"]([]) == []
    finally:
        rt.stop()


def test_wave3_tier_moves():
    """W3.5/W3.8: the registry re-assertions landed — Await/Poll/Sleep and
    the new tools are core; messenger is demoted to advanced."""
    from dhc.framework.surface import default_registry

    for name in ("Await", "Poll", "Sleep", "gather", "ack", "answers"):
        entry = default_registry.get(name)
        assert entry is not None, f"{name} not registered"
        assert entry.tier == "core", f"{name} should be core, is {entry.tier}"
    assert default_registry.get("Await").call == "Await(handle)"
    assert default_registry.get("Poll").call == "Poll(handle)"
    assert default_registry.get("Sleep").call == "Sleep(seconds)"
    assert default_registry.get("messenger").tier == "advanced"
    # Advanced entries stay listed (reachable, not advertised).
    listed = default_registry.list_tools()
    assert "messenger" in listed
    assert "channel_read" in listed


def test_prompt_teaches_wave3_surface():
    """W3.5/W3.6/W3.8: the generated prompt picks up every tier move —
    the two await idioms, gather, ack/answers — and no longer teaches
    messenger.send (demoted)."""
    from dhc.llm.driver import default_build_prompt

    class _ProbeStatus:
        done = False
        ok = False
        reason = "not settled"

    class _ProbeAgent:
        requirement = "wave3 probe"
        acceptance = ("probe done",)

        def status(self):
            return _ProbeStatus()

    prompt = default_build_prompt(_ProbeAgent())
    assert "Await(handle)" in prompt
    assert "Poll(handle)" in prompt
    assert "Sleep(seconds)" in prompt
    assert "gather(handles" in prompt
    assert "ack(escalation_id)" in prompt
    assert "answers(question_id)" in prompt
    assert "messenger.send" not in prompt


# --------------------------------------------------------------------------- #
# Wave 3 acceptance: every prompt-visible verb has an end-to-end usage test
# in tests/tooling/ (the runtime-core verbs are exercised here through a
# fully wired runtime, the way an agent's block actually calls them).
# --------------------------------------------------------------------------- #


def _block_runtime(tmp_path):
    """A started mock runtime whose agents run real blocks."""
    from dhc import build_runtime

    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    return rt


def test_core_verbs_end_to_end_spawn_await_poll(tmp_path):
    """spawn/await_/poll/status/result/children_of/complete/fail/cancel
    work end-to-end from an agent block (the prompt-visible call forms)."""
    from dhc.data.models import AgentStatus

    rt = _block_runtime(tmp_path)
    try:
        parent = rt.spawn(
            "parent",
            driver=MockDriver.single(
                "c = spawn('child', driver=child_driver)\n"
                "s = poll(c)\n"
                "done = await_(c)\n"
                "kids = children_of(agent)\n"
                "st = status()\n"
                "r = result()\n"
                "complete('parent saw ' + done.summary, artifacts=())\n"
            ),
            namespace={"child_driver": MockDriver.single("complete('child done')")},
        )
        completion = parent.await_()
        assert completion.status == AgentStatus.completed
        ws = rt.repl_engine.globals_for(parent.id)
        assert ws["done"].status == AgentStatus.completed
        assert ws["done"].summary == "child done"
        assert ws["kids"] == [ws["done"].agent_id]  # ids, not handles
        assert ws["st"].done is False  # the parent itself was still running
        assert ws["r"] is None or ws["r"].ok is False
    finally:
        rt.stop()


def test_core_verbs_end_to_end_send_and_fail(tmp_path):
    """send delivers to the recipient's events tool; fail settles the
    agent as failed — both from agent blocks."""
    from dhc.data.models import AgentStatus

    from dhc.data.models import EventKind

    rt = _block_runtime(tmp_path)
    try:
        receiver = rt.spawn("receiver", driver=MockDriver.single("complete('r')"))
        sender = rt.spawn(
            "sender",
            driver=MockDriver.single(
                "send(recipient, 'hello from a block')\nfail('cannot proceed')\n"
            ),
            namespace={"recipient": receiver.id},
        )
        c_sender = sender.await_()
        assert c_sender.status == AgentStatus.failed
        assert c_sender.reason == "cannot proceed"
        receiver.await_()
        seen = [
            e for e in rt.tool_events(receiver.id)
            if e.kind == EventKind.message_sent
        ]
        assert [e.payload["body"] for e in seen] == ["hello from a block"]
    finally:
        rt.stop()


def test_core_verbs_end_to_end_yield_forms(tmp_path):
    """The yield idiom (Await/Poll/Sleep) works from an agent block."""
    from dhc.data.models import AgentStatus

    rt = _block_runtime(tmp_path)
    try:
        parent = rt.spawn(
            "parent",
            driver=MockDriver.single(
                "__runner = '''def __runner__(ctx):\n"
                "    c = spawn('child', driver=child_driver)\n"
                "    yield Poll(c)\n"
                "    yield Sleep(0.01)\n"
                "    done = await_(c)\n"
                "    complete('yielded then joined: ' + done.summary)\n"
                "'''\n"
            ),
            namespace={"child_driver": MockDriver.single("complete('child done')")},
        )
        completion = parent.await_()
        assert completion.status == AgentStatus.completed
        assert "yielded then joined: child done" == completion.summary
    finally:
        rt.stop()


def test_core_verbs_end_to_end_tool_and_bash(tmp_path):
    """tool(callable, *args) and bash(cmd) run from an agent block."""
    from dhc.data.models import AgentStatus

    rt = _block_runtime(tmp_path)
    try:
        agent = rt.spawn(
            "t",
            driver=MockDriver.single(
                "out = tool(len, 'hello')\n"
                "sh = bash('echo hi')\n"
                "complete(f'{out.text} {sh.strip()}')\n"
            ),
        )
        completion = agent.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "5 hi"
        ws = rt.repl_engine.globals_for(agent.id)
        assert ws["out"].text == "5" and ws["out"].ok
    finally:
        rt.stop()


def test_core_verbs_end_to_end_record_result(tmp_path):
    """record_result(reason) from a block records the reason and settles the agent.

    NOTE: this pins the CURRENT contract — the block-side ``record_result``
    verb (``Agent.record_result``) records a not-ok last result, which the
    pump settles as *failed* with that reason; only ``Runtime.cancel``
    settles as *cancelled*. The two-behavior split is review finding F9 (a
    later wave); Wave 3 only guarantees the verb is callable end-to-end and
    the reason survives. (W4.4: the verb was renamed from ``cancel`` to
    ``record_result`` — a method named cancel that does not cancel is a
    trap; ``AgentHandle.cancel`` is the real cancel.)
    """
    from dhc.data.models import AgentStatus

    rt = _block_runtime(tmp_path)
    try:
        agent = rt.spawn(
            "c",
            driver=MockDriver.single("record_result('no longer needed')\n"),
        )
        completion = agent.await_()
        assert completion.status == AgentStatus.failed
        assert completion.reason == "no longer needed"
    finally:
        rt.stop()
