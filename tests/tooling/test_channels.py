"""Tests for dhc.tooling.channels: Messenger, RoomManager, EscalationChannel,
OperatorQuestionChannel.

Decision 0015: direct messaging is a framework primitive (``Runtime.send`` —
receiver-addressed ``message_sent`` events on the recipient's stream); these
channels are tooling policies over that primitive. Covers INFO-011/015/016/023
semantics: the Messenger inbox/read-state *view* over receiver-addressed
message events, shared rooms with membership enforcement and traffic
persistence, upstream escalation with by-reference payload and ack, and
operator questions with causal_id-linked answers.
"""

import pytest

from dhc.tooling.channels import (
    EscalationChannel,
    Messenger,
    OperatorQuestionChannel,
    RoomManager,
)
from dhc.errors import ChannelError
from dhc.data.models import Event, EventKind, Message, Room


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


def _message_event(sender_id: str, recipient_id: str, body: str, message_id: str = "m1") -> Event:
    """A receiver-addressed message event, as ``Runtime.send`` emits it (0015)."""
    return Event(
        kind=EventKind.message_sent,
        agent_id=recipient_id,
        payload={"sender_id": sender_id, "message_id": message_id, "body": body},
    )


# --------------------------------------------------------------------------- #
# Messenger — INFO-015 (a view over the core message events)
# --------------------------------------------------------------------------- #


def test_messenger_view_inbox_read_unread_fifo():
    bus = _FakeBus()
    m = Messenger(bus)

    bus.publish(_message_event("alice", "bob", "first", "m1"))
    bus.publish(_message_event("alice", "bob", "second", "m2"))
    bus.publish(_message_event("bob", "alice", "reply", "m3"))

    # FIFO order per recipient.
    assert [msg.body for msg in m.inbox("bob")] == ["first", "second"]
    assert [msg.body for msg in m.inbox("alice")] == ["reply"]

    # Unread counts.
    assert m.unread_count("bob") == 2
    assert m.unread_count("alice") == 1

    # read() marks one message read and returns it.
    got = m.read("bob", "m1")
    assert got is not None and got.body == "first"
    assert m.unread_count("bob") == 1

    # Reading an unknown id returns None.
    assert m.read("bob", "nope") is None

    # The rebuilt Messages carry sender/recipient/body from the event.
    reply = m.inbox("alice")[0]
    assert isinstance(reply, Message)
    assert reply.sender_id == "bob"
    assert reply.recipient_id == "alice"
    assert reply.body == "reply"


def test_messenger_ignores_non_message_events():
    bus = _FakeBus()
    m = Messenger(bus)
    bus.publish(Event(kind=EventKind.room_message, agent_id="bob", payload={}))
    bus.publish(Event(kind=EventKind.escalation, agent_id="bob", payload={}))
    assert m.inbox("bob") == []
    assert m.unread_count("bob") == 0


def test_messenger_is_a_view_delivery_is_core():
    """The Messenger is a VIEW over the stream (decision 0015): with no
    Messenger, a receiver-addressed message event still lands on the
    recipient's stream — the runtime's send delivers, not the channel."""
    from dhc.framework.event_stream import EventBus

    bus = EventBus()
    bus.publish(_message_event("alice", "bob", "hi"))
    events = bus.stream_for("bob").drain()
    assert [e.kind for e in events] == [EventKind.message_sent]

    # A Messenger constructed after the fact views live traffic only; the
    # stream already delivered. The channel adds read-state sugar, not
    # delivery.
    m = Messenger(bus)
    assert m.inbox("bob") == []


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
