"""Tests for dhc.communication: Messenger, RoomManager, EscalationChannel,
OperatorQuestionChannel.

Covers INFO-011/015/016/023 semantics: direct FIFO messaging with unknown-
recipient ChannelError, shared rooms with membership enforcement and traffic
persistence, upstream escalation with by-reference payload and ack, and
operator questions with causal_id-linked answers.
"""

import pytest

from dhc.communication import (
    EscalationChannel,
    Messenger,
    OperatorQuestionChannel,
    RoomManager,
)
from dhc.errors import ChannelError
from dhc.models import Event, EventKind, Message, Room


class _FakeBus:
    """Duck-typed EventBus: records published events, invokes global listeners."""

    def __init__(self) -> None:
        self.published: list[Event] = []
        self._globals = []

    def publish(self, event: Event) -> None:
        self.published.append(event)
        for cb in self._globals:
            cb(event)

    def subscribe_global(self, callback) -> None:
        self._globals.append(callback)


class _Sink:
    """Recording sink: duck-typed ``append``."""

    def __init__(self) -> None:
        self.records = []

    def append(self, record) -> None:
        self.records.append(record)

    def __iter__(self):
        return iter(self.records)


class _Registry:
    def __init__(self, ids) -> None:
        self._ids = set(ids)

    def __contains__(self, agent_id: str) -> bool:
        return agent_id in self._ids


# --------------------------------------------------------------------------- #
# Messenger — INFO-015
# --------------------------------------------------------------------------- #


def test_messenger_send_inbox_read_unread_fifo():
    bus = _FakeBus()
    registry = _Registry({"alice", "bob"})
    m = Messenger(bus, registry)

    m1 = m.send("alice", "bob", "first")
    m2 = m.send("alice", "bob", "second")
    m3 = m.send("bob", "alice", "reply")

    # FIFO order per recipient.
    assert [msg.body for msg in m.inbox("bob")] == ["first", "second"]
    assert [msg.body for msg in m.inbox("alice")] == ["reply"]

    # Unread counts.
    assert m.unread_count("bob") == 2
    assert m.unread_count("alice") == 1

    # read() marks one message read and returns it.
    first_id = m.inbox("bob")[0].body  # body is not the id; find by content below
    # Locate the message id via the event payload.
    sent_events = [e for e in bus.published if e.kind == EventKind.message_sent]
    assert len(sent_events) == 3
    first_event = sent_events[0]
    assert first_event.payload["recipient_id"] == "bob"
    first_message_id = first_event.payload["message_id"]

    got = m.read("bob", first_message_id)
    assert got is not None and got.body == "first"
    assert m.unread_count("bob") == 1

    # Reading an unknown id returns None.
    assert m.read("bob", "nope") is None

    # Events carry the correct kind.
    assert all(e.kind == EventKind.message_sent for e in sent_events)


def test_messenger_send_unknown_recipient_raises():
    bus = _FakeBus()
    registry = _Registry({"alice"})
    m = Messenger(bus, registry)
    with pytest.raises(ChannelError):
        m.send("alice", "ghost", "hello")
    assert bus.published == []


def test_messenger_sink_persists_messages():
    sink = _Sink()
    bus = _FakeBus()
    registry = _Registry({"alice", "bob"})
    m = Messenger(bus, registry, sink=sink)
    m.send("alice", "bob", "durable")
    assert len(sink.records) == 1
    assert isinstance(sink.records[0], Message)
    assert sink.records[0].body == "durable"


# --------------------------------------------------------------------------- #
# RoomManager — INFO-016
# --------------------------------------------------------------------------- #


def test_room_join_post_messages_members_leave():
    bus = _FakeBus()
    rm = RoomManager(bus)

    room = rm.join("alice", "general")
    assert isinstance(room, Room)
    assert room.name == "general"
    assert rm.members("general") == ["alice"]
    assert rm.rooms() == ["general"]

    rm.join("bob", "general")
    assert rm.members("general") == ["alice", "bob"]

    msg = rm.post("alice", "general", "hello room")
    assert msg.body == "hello room"
    assert [m.body for m in rm.messages("general")] == ["hello room"]

    # Non-member cannot post.
    with pytest.raises(ChannelError):
        rm.post("carol", "general", "intruder")

    # Leave then post raises.
    rm.leave("alice", "general")
    assert rm.members("general") == ["bob"]
    with pytest.raises(ChannelError):
        rm.post("alice", "general", "after leave")

    # Events carry the correct kind.
    room_events = [e for e in bus.published if e.kind == EventKind.room_message]
    assert len(room_events) == 1
    assert room_events[0].payload["room_name"] == "general"


def test_room_traffic_persists_across_managers_with_sink():
    sink = _Sink()
    bus1 = _FakeBus()
    rm1 = RoomManager(bus1, sink=sink)
    rm1.join("alice", "general")
    rm1.post("alice", "general", "persisted")

    bus2 = _FakeBus()
    rm2 = RoomManager(bus2, sink=sink)
    assert [m.body for m in rm2.messages("general")] == ["persisted"]


def test_room_traffic_persists_across_managers_with_shared_rooms():
    rooms: dict[str, Room] = {}
    rm1 = RoomManager(_FakeBus(), rooms=rooms)
    rm1.join("alice", "general")
    rm1.post("alice", "general", "persisted")

    rm2 = RoomManager(_FakeBus(), rooms=rooms)
    assert [m.body for m in rm2.messages("general")] == ["persisted"]
    assert rm2.members("general") == ["alice"]


# --------------------------------------------------------------------------- #
# EscalationChannel — INFO-011
# --------------------------------------------------------------------------- #


def test_escalation_emits_event_with_by_reference_payload_pending_ack():
    bus = _FakeBus()
    ch = EscalationChannel(bus)

    event = ch.escalate("child", "parent", "requirement-x", "unreachable")
    assert event.kind == EventKind.escalation
    assert event.agent_id == "parent"
    assert event.payload["requirement"] == "requirement-x"
    assert event.payload["reason"] == "unreachable"
    assert event.payload["child_id"] == "child"
    event_id = event.payload["event_id"]

    # The bus saw the escalation event.
    assert [e.kind for e in bus.published] == [EventKind.escalation]

    # Pending for the parent; not visible to others.
    pending = ch.pending_for("parent")
    assert len(pending) == 1
    assert pending[0].payload["event_id"] == event_id
    assert ch.pending_for("other") == []

    # Ack removes it from pending.
    ch.ack("parent", event_id)
    assert ch.pending_for("parent") == []

    # Double ack raises.
    with pytest.raises(ChannelError):
        ch.ack("parent", event_id)


def test_escalation_ack_unknown_raises():
    ch = EscalationChannel(_FakeBus())
    with pytest.raises(ChannelError):
        ch.ack("parent", "no-such-event")


# --------------------------------------------------------------------------- #
# OperatorQuestionChannel — INFO-023
# --------------------------------------------------------------------------- #


def test_operator_question_ask_pending_answer_causal_answers_for():
    bus = _FakeBus()
    ch = OperatorQuestionChannel(bus)

    q = ch.ask("inner", "may I proceed?")
    assert q.kind == EventKind.operator_question
    assert q.agent_id == "inner"
    question_id = q.payload["event_id"]

    assert [e.kind for e in bus.published] == [EventKind.operator_question]
    pending = ch.pending_questions()
    assert len(pending) == 1
    assert pending[0].payload["question"] == "may I proceed?"

    ans = ch.answer(question_id, "yes", operator_id="op-1")
    assert ans.kind == EventKind.operator_answer
    assert ans.causal_id == question_id
    assert ans.agent_id == "inner"
    assert ans.payload["answer"] == "yes"
    assert ans.payload["operator_id"] == "op-1"

    # Question no longer pending; answer routed to the asking agent.
    assert ch.pending_questions() == []
    answers = ch.answers_for("inner")
    assert len(answers) == 1
    assert answers[0].causal_id == question_id

    # Answering again raises.
    with pytest.raises(ChannelError):
        ch.answer(question_id, "no")


def test_operator_question_answer_unknown_raises():
    ch = OperatorQuestionChannel(_FakeBus())
    with pytest.raises(ChannelError):
        ch.answer("no-such-question", "yes")