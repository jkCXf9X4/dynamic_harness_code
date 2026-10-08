"""Tests for dhc.models and dhc.errors."""

from datetime import datetime

import pytest
from pydantic import ValidationError

import dhc
from dhc.errors import (
    AgentCancelledError,
    AgentCrashedError,
    ArtifactNotFoundError,
    ChannelError,
    ConfigError,
    DhcError,
    TurnError,
    TurnTimeoutError,
)
from dhc.data.models import (
    TERMINAL_STATES,
    AgentStatus,
    Artifact,
    Completion,
    CompletionLog,
    Event,
    EventKind,
    Message,
    Result,
    Room,
    ToolOutput,
    Turn,
    is_terminal,
)


# --------------------------------------------------------------------------- #
# Package surface
# --------------------------------------------------------------------------- #


def test_version():
    assert dhc.__version__ == "0.1.0"


def test_public_surface():
    for name in (
        "Artifact",
        "Result",
        "Event",
        "EventKind",
        "AgentStatus",
        "Completion",
        "ToolOutput",
        "Message",
        "Room",
        "Turn",
        "DhcError",
        "TurnError",
        "TurnTimeoutError",
        "AgentCancelledError",
        "AgentCrashedError",
        "ArtifactNotFoundError",
        "ChannelError",
        "ConfigError",
    ):
        assert hasattr(dhc, name), f"dhc.{name} missing"


# --------------------------------------------------------------------------- #
# Artifact
# --------------------------------------------------------------------------- #


def test_artifact_requires_headline_summary_report():
    with pytest.raises(ValidationError):
        Artifact()


def test_artifact_content_addressed_id_format():
    a = Artifact(headline="h", summary="s", report="body")
    assert a.id.startswith("sha256:")
    assert len(a.id) == len("sha256:") + 64  # sha256 hex digest


def test_artifact_id_deterministic():
    a1 = Artifact(headline="h", summary="s", report="same body")
    a2 = Artifact(headline="h", summary="s", report="same body")
    assert a1.id == a2.id


def test_artifact_id_changes_with_content():
    a1 = Artifact(headline="h", summary="s", report="body one")
    a2 = Artifact(headline="h", summary="s", report="body two")
    assert a1.id != a2.id


def test_artifact_id_is_content_addressed_over_body():
    # same body, different headline/summary -> same content address
    a1 = Artifact(headline="h1", summary="s1", report="same body")
    a2 = Artifact(headline="h2", summary="s2", report="same body")
    assert a1.id == a2.id


def test_artifact_rejects_mismatched_id():
    with pytest.raises(ValidationError):
        Artifact(id="sha256:" + "0" * 64, headline="h", summary="s", report="body")


def test_artifact_content_helper():
    a = Artifact(headline="h", summary="s", report="full body")
    assert a.content() == "full body"


def test_artifact_content_serializes_structured_report():
    a = Artifact(headline="h", summary="s", report={"a": 1, "b": [2, 3]})
    assert '"a": 1' in a.content()


def test_artifact_immutable():
    a = Artifact(headline="h", summary="s", report="body")
    with pytest.raises(ValueError):
        a.headline = "changed"


# --------------------------------------------------------------------------- #
# Result
# --------------------------------------------------------------------------- #


def test_result_defaults():
    r = Result(done=True, ok=True)
    assert r.value is None
    assert r.reason == ""
    assert r.artifacts == []


def test_result_artifacts_are_ids():
    r = Result(done=True, ok=True, value="done", artifacts=["sha256:abc"])
    assert r.artifacts == ["sha256:abc"]


def test_result_requires_done_and_ok():
    with pytest.raises(ValidationError):
        Result(done=True)


# --------------------------------------------------------------------------- #
# Event / EventKind
# --------------------------------------------------------------------------- #


def test_event_kind_members():
    assert {k.value for k in EventKind} == {
        "turn_started",
        "turn_completed",
        "turn_failed",
        "artifact_published",
        "child_spawned",
        "child_settled",
        "message_sent",
        "room_message",
        "escalation",
        "cancelled",
        "timeout",
        "crash",
        "operator_question",
        "operator_answer",
    }


def test_event_defaults():
    e = Event(kind=EventKind.turn_started, agent_id="a1")
    assert e.causal_id is None
    assert e.payload == {}
    assert isinstance(e.ts, datetime)


def test_event_payload_is_by_reference():
    e = Event(
        kind=EventKind.child_settled,
        agent_id="a1",
        payload={"child_ids": ["c1"], "artifact_ids": ["sha256:x"]},
    )
    assert e.payload["child_ids"] == ["c1"]


def test_event_requires_kind_and_agent():
    with pytest.raises(ValidationError):
        Event(kind=EventKind.crash)


# --------------------------------------------------------------------------- #
# AgentStatus / TerminalState
# --------------------------------------------------------------------------- #


def test_agent_status_members():
    assert {s.value for s in AgentStatus} == {
        "pending",
        "running",
        "completed",
        "failed",
        "cancelled",
        "timeout",
    }


@pytest.mark.parametrize(
    "status",
    [
        AgentStatus.completed,
        AgentStatus.failed,
        AgentStatus.cancelled,
        AgentStatus.timeout,
    ],
)
def test_is_terminal_true(status):
    assert is_terminal(status)


@pytest.mark.parametrize("status", [AgentStatus.pending, AgentStatus.running])
def test_is_terminal_false(status):
    assert not is_terminal(status)


def test_terminal_states_constant():
    assert TERMINAL_STATES == frozenset(
        {
            AgentStatus.completed,
            AgentStatus.failed,
            AgentStatus.cancelled,
            AgentStatus.timeout,
        }
    )


# --------------------------------------------------------------------------- #
# Completion / at-most-once
# --------------------------------------------------------------------------- #


def test_completion_defaults():
    c = Completion(agent_id="a1", status=AgentStatus.completed)
    assert c.summary == ""
    assert c.artifact_ids == []
    assert c.reason == ""


def test_completion_requires_terminal_status():
    with pytest.raises(ValidationError):
        Completion(agent_id="a1", status=AgentStatus.running)


def test_completion_immutable():
    c = Completion(agent_id="a1", status=AgentStatus.completed)
    with pytest.raises(ValueError):
        c.status = AgentStatus.failed


def test_completion_at_most_once():
    log = CompletionLog()
    first = log.settle(
        Completion(agent_id="a1", status=AgentStatus.completed, summary="done")
    )
    assert log.get("a1") is first
    assert "a1" in log
    assert len(log) == 1
    with pytest.raises(ChannelError):
        log.settle(Completion(agent_id="a1", status=AgentStatus.failed, reason="late"))
    # first settlement wins
    assert log.get("a1") is first


def test_completion_log_distinct_agents():
    log = CompletionLog()
    log.settle(Completion(agent_id="a1", status=AgentStatus.completed))
    log.settle(Completion(agent_id="a2", status=AgentStatus.failed, reason="nope"))
    assert len(log) == 2


# --------------------------------------------------------------------------- #
# ToolOutput
# --------------------------------------------------------------------------- #


def test_tool_output_minted():
    out = ToolOutput.minted("hello")
    assert out.text == "hello"
    assert out.id


def test_tool_output_search():
    out = ToolOutput(text="line one\nFAILED: boom\nline three")
    assert out.search("FAILED") == [(2, "FAILED: boom")]


def test_tool_output_search_limit():
    out = ToolOutput(text="x\nFAILED\nFAILED\nFAILED")
    assert len(out.search("FAILED", limit=2)) == 2


def test_tool_output_read():
    out = ToolOutput(text="0123456789")
    assert out.read(size=4, offset=2) == "2345"


# --------------------------------------------------------------------------- #
# Message / Room / Turn
# --------------------------------------------------------------------------- #


def test_message_defaults():
    m = Message(sender_id="a", recipient_id="b", body="hi")
    assert isinstance(m.ts, datetime)


def test_room_defaults():
    r = Room(name="war-room")
    assert r.member_ids == []
    assert r.messages == []


def test_room_holds_messages():
    m = Message(sender_id="a", recipient_id="b", body="hi")
    r = Room(name="war-room", member_ids=["a", "b"], messages=[m])
    assert r.messages[0].body == "hi"


def test_turn_defaults():
    t = Turn(code="print(1)", agent_id="a1")
    assert isinstance(t.ts, datetime)


# --------------------------------------------------------------------------- #
# Errors
# --------------------------------------------------------------------------- #


def test_error_hierarchy():
    assert issubclass(TurnError, DhcError)
    assert issubclass(TurnTimeoutError, TurnError)
    assert issubclass(AgentCancelledError, DhcError)
    assert issubclass(AgentCrashedError, DhcError)
    assert issubclass(ArtifactNotFoundError, DhcError)
    assert issubclass(ChannelError, DhcError)
    assert issubclass(ConfigError, DhcError)