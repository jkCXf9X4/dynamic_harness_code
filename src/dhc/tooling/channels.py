"""Communication channels: policies over the core message primitive.

Operator tooling (decision 0015): direct agent-to-agent messaging is a
framework primitive (``Runtime.send`` / ``Agent.send``) — a
receiver-addressed ``message_sent`` event delivered on the recipient's own
stream. Everything above that primitive is a *policy* this package composes,
so the agent keeps full control of its communication (use, replace, or
ignore each channel):

* :class:`Messenger` — per-recipient inbox/read-state view over the core
  message events (INFO-015). A *view*, not a delivery mechanism: with no
  Messenger installed, messages still arrive (digest, recent context,
  ``events`` tool).
* :class:`RoomManager` — shared rooms, many-to-many (INFO-016).
* :class:`EscalationChannel` — escalate an unreachable requirement up the
  parent chain (INFO-011).
* :class:`OperatorQuestionChannel` — any agent can ask the operator a
  question (INFO-023).

Every channel takes the injected :class:`~dhc.agent.event_stream.EventBus`
(duck-typed: ``publish(event)``, ``subscribe_global(callback)``) so tests can
use a fake bus. Events carry the correct :class:`~dhc.data.models.EventKind`
and payloads are by reference (ids / short values, never live handles).
Channel misuse raises :class:`~dhc.errors.ChannelError`.
"""

from __future__ import annotations

import threading
import uuid
from typing import Optional

from ..errors import ChannelError
from ..data.models import Event, EventKind, Message, Room


def _new_id() -> str:
    return uuid.uuid4().hex


def _to_message(event: Event) -> Message:
    """Rebuild the tool-facing :class:`Message` from a message event."""
    return Message(
        sender_id=str(event.payload.get("sender_id", "")),
        recipient_id=event.agent_id,
        body=str(event.payload.get("body", "")),
    )


class Messenger:
    """Per-recipient inbox view over the core message primitive (INFO-015).

    Delivery is framework-owned (decision 0015): ``Runtime.send`` emits a
    receiver-addressed ``message_sent`` event on the recipient's own event
    stream, so the message arrives in the recipient's digest, recent
    context, and ``events`` tool *whether or not this channel exists*.
    This channel is a *view*: it observes the global feed, files each
    recipient's messages in arrival (FIFO) order, and tracks reads. It
    owns no delivery queues — the stream is the single source of truth,
    and sending goes through the runtime's ``send`` (the tooling facade
    in :mod:`dhc.tooling.channel_tools` calls it).
    """

    def __init__(self, bus) -> None:
        self._bus = bus
        # recipient_id -> [(message_id, Event, read_flag)] in arrival order.
        self._seen: dict[str, list[tuple[str, Event, bool]]] = {}
        self._lock = threading.RLock()
        bus.subscribe_global(self._on_event)

    def _on_event(self, event: Event) -> None:
        if event.kind is not EventKind.message_sent:
            return
        message_id = str(event.payload.get("message_id", ""))
        with self._lock:
            self._seen.setdefault(event.agent_id, []).append(
                (message_id, event, False)
            )

    def inbox(self, agent_id: str) -> list[Message]:
        """Return all messages for *agent_id* in arrival (FIFO) order."""
        with self._lock:
            return [_to_message(entry) for _, entry, _ in
                    self._seen.get(agent_id, [])]

    def read(self, agent_id: str, message_id: str) -> Message | None:
        """Mark the message *message_id* as read and return it (or ``None``)."""
        with self._lock:
            entries = self._seen.get(agent_id, [])
            for i, (mid, event, _) in enumerate(entries):
                if mid == message_id:
                    entries[i] = (mid, event, True)
                    return _to_message(event)
        return None

    def unread_count(self, agent_id: str) -> int:
        """Number of messages for *agent_id* not yet read."""
        with self._lock:
            return sum(1 for _, _, read in self._seen.get(agent_id, []) if not read)


class RoomManager:
    """Shared rooms, many-to-many (INFO-016).

    Rooms are created on first join; membership is visible to all members.
    Room traffic persists in the room for the room's lifetime. An optional
    duck-typed ``sink`` (``sink.append(record)``) persists room traffic so a
    new manager over the same sink restores it; alternatively pass a shared
    ``rooms`` dict for in-memory persistence across instances. Sink records
    are ``("room_message", room_name, Message)`` tuples.
    """

    def __init__(
        self,
        bus,
        sink: Optional[object] = None,
        rooms: Optional[dict[str, Room]] = None,
    ) -> None:
        self._bus = bus
        self._sink = sink
        self._rooms: dict[str, Room] = rooms if rooms is not None else {}
        self._lock = threading.RLock()
        if sink is not None:
            self._replay(sink)

    def _replay(self, sink: object) -> None:
        """Restore room traffic from a previously written sink."""
        if not hasattr(sink, "__iter__"):
            return
        for record in sink:
            if not isinstance(record, tuple) or len(record) != 3:
                continue
            kind, room_name, message = record
            if kind != "room_message" or not isinstance(message, Message):
                continue
            room = self._rooms.get(room_name)
            if room is None:
                room = Room(name=room_name)
                self._rooms[room_name] = room
            room.messages.append(message)

    def join(self, agent_id: str, room_name: str) -> Room:
        """Join *room_name*, creating it on first join; return the room."""
        with self._lock:
            room = self._rooms.get(room_name)
            if room is None:
                room = Room(name=room_name)
                self._rooms[room_name] = room
            if agent_id not in room.member_ids:
                room.member_ids.append(agent_id)
            return room

    def leave(self, agent_id: str, room_name: str) -> None:
        """Leave *room_name*; a no-op if the agent is not a member."""
        with self._lock:
            room = self._rooms.get(room_name)
            if room is None:
                return
            if agent_id in room.member_ids:
                room.member_ids.remove(agent_id)

    def post(self, agent_id: str, room_name: str, body: str) -> Message:
        """Post *body* to *room_name* as *agent_id*.

        Emits a ``room_message`` event on the bus; raises ``ChannelError`` if
        the agent is not a member of the room.
        """
        with self._lock:
            room = self._rooms.get(room_name)
            if room is None or agent_id not in room.member_ids:
                raise ChannelError(
                    f"agent {agent_id!r} is not a member of room {room_name!r}"
                )
            message = Message(sender_id=agent_id, recipient_id=room_name, body=body)
            room.messages.append(message)
        if self._sink is not None:
            self._sink.append(("room_message", room_name, message))
        self._bus.publish(
            Event(
                kind=EventKind.room_message,
                agent_id=agent_id,
                payload={"room_name": room_name},
            )
        )
        return message

    def messages(self, room_name: str) -> list[Message]:
        """Return the room's traffic in post order (empty for unknown rooms)."""
        with self._lock:
            room = self._rooms.get(room_name)
            return list(room.messages) if room is not None else []

    def members(self, room_name: str) -> list[str]:
        """Return the room's member ids (empty for unknown rooms)."""
        with self._lock:
            room = self._rooms.get(room_name)
            return list(room.member_ids) if room is not None else []

    def rooms(self) -> list[str]:
        """Return the names of all known rooms."""
        with self._lock:
            return list(self._rooms.keys())


class EscalationChannel:
    """Escalate an unreachable requirement up the parent chain (INFO-011).

    The parent chain is caller-supplied (``parent_id``); the runtime wires it.
    Escalation travels upstream only (child -> parent). The emitted event is
    addressed to the parent (``event.agent_id == parent_id``) and carries
    ``{requirement, reason}`` in its payload by reference, plus an
    ``event_id`` used by :meth:`ack`.
    """

    def __init__(self, bus) -> None:
        self._bus = bus
        # parent_id -> [escalation events] in emit order.
        self._pending: dict[str, list[Event]] = {}
        self._acked: set[str] = set()
        self._lock = threading.RLock()
        bus.subscribe_global(self._on_event)

    def _on_event(self, event: Event) -> None:
        if event.kind != EventKind.escalation:
            return
        with self._lock:
            self._pending.setdefault(event.agent_id, []).append(event)

    def escalate(
        self, agent_id: str, parent_id: str, requirement: str, reason: str
    ) -> Event:
        """Escalate *requirement*/*reason* from *agent_id* to *parent_id*."""
        event = Event(
            kind=EventKind.escalation,
            agent_id=parent_id,
            payload={
                "event_id": _new_id(),
                "child_id": agent_id,
                "requirement": requirement,
                "reason": reason,
            },
        )
        self._bus.publish(event)
        return event

    def pending_for(self, agent_id: str) -> list[Event]:
        """Return unacknowledged escalations addressed to *agent_id*."""
        with self._lock:
            return [
                e
                for e in self._pending.get(agent_id, [])
                if e.payload.get("event_id") not in self._acked
            ]

    def ack(self, agent_id: str, event_id: str) -> None:
        """Acknowledge escalation *event_id* for *agent_id*.

        Raises ``ChannelError`` if the event is not a pending escalation for
        that agent (unknown or already acknowledged).
        """
        with self._lock:
            pending = self._pending.get(agent_id, [])
            if not any(e.payload.get("event_id") == event_id for e in pending):
                raise ChannelError(
                    f"no pending escalation {event_id!r} for agent {agent_id!r}"
                )
            if event_id in self._acked:
                raise ChannelError(
                    f"escalation {event_id!r} already acknowledged"
                )
            self._acked.add(event_id)


class OperatorQuestionChannel:
    """Any agent can ask the operator a question (INFO-023).

    The question routes up the parent chain to the root and crosses to the
    operator; the answer routes back down the same chain to the asking agent.
    Asking is a normal channel state, not a failure. The answer event carries
    ``causal_id`` = the question event's id.
    """

    def __init__(self, bus) -> None:
        self._bus = bus
        # event_id -> question event.
        self._questions: dict[str, Event] = {}
        self._answers: list[Event] = []
        self._answered: set[str] = set()
        self._lock = threading.RLock()
        bus.subscribe_global(self._on_event)

    def _on_event(self, event: Event) -> None:
        if event.kind == EventKind.operator_question:
            with self._lock:
                self._questions[event.payload["event_id"]] = event
        elif event.kind == EventKind.operator_answer:
            with self._lock:
                self._answers.append(event)
                if event.causal_id is not None:
                    self._answered.add(event.causal_id)

    def ask(self, agent_id: str, question: str) -> Event:
        """Ask the operator *question* as *agent_id*; return the event."""
        event = Event(
            kind=EventKind.operator_question,
            agent_id=agent_id,
            payload={"event_id": _new_id(), "question": question},
        )
        self._bus.publish(event)
        return event

    def pending_questions(self) -> list[Event]:
        """Return questions not yet answered, in ask order."""
        with self._lock:
            return [
                q
                for q in self._questions.values()
                if q.payload["event_id"] not in self._answered
            ]

    def answer(
        self, question_event_id: str, answer: str, operator_id: str = "operator"
    ) -> Event:
        """Answer question *question_event_id*; return the answer event.

        The answer event's ``causal_id`` links to the question event id and
        its ``agent_id`` is the asking agent. Raises ``ChannelError`` for an
        unknown or already-answered question.
        """
        with self._lock:
            question = self._questions.get(question_event_id)
            if question is None:
                raise ChannelError(f"unknown question {question_event_id!r}")
            if question_event_id in self._answered:
                raise ChannelError(f"question {question_event_id!r} already answered")
            asking_agent = question.agent_id
            self._answered.add(question_event_id)
        event = Event(
            kind=EventKind.operator_answer,
            agent_id=asking_agent,
            causal_id=question_event_id,
            payload={
                "event_id": _new_id(),
                "answer": answer,
                "operator_id": operator_id,
            },
        )
        self._bus.publish(event)
        return event

    def answers_for(self, agent_id: str) -> list[Event]:
        """Return answers routed back to *agent_id*, in answer order."""
        with self._lock:
            return [a for a in self._answers if a.agent_id == agent_id]
