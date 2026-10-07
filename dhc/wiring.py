"""Wiring: build a fully-wired Runtime from the real committed modules.

The committed :class:`~dhc.runtime.Runtime` was written against lightweight
in-memory duck-types (``_MemoryEngine``, ``_MemoryBus``, ``_MemoryStore``)
with a topic-based bus contract (``publish(topic, event)`` /
``drain(topic)``). The real modules have richer contracts:

* :class:`~dhc.repl.ReplEngine.execute` returns a :class:`~dhc.models.Result`
  and never raises (failures are values, INFO-020), while the runtime expects
  a raising engine (it catches ``TurnTimeoutError`` / ``Exception``).
* :class:`~dhc.event_stream.EventBus.publish(event)` takes one argument and
  routes by ``event.agent_id``; the runtime calls ``publish(topic, event)``.
* :class:`~dhc.artifact_store.ArtifactStore` has ``put(artifact)``, while the
  in-code surface calls ``store.publish(headline, summary, report)``.

:func:`build_runtime` bridges these seams with small adapters (all in this
file — no committed module is edited) and wires the real modules together:

* :class:`~dhc.repl.ReplEngine` — per-agent persistent REPL (INFO-050)
* :class:`~dhc.event_stream.EventBus` with the
  :class:`~dhc.artifact_store.BoundaryEventLog` as its persist sink (INFO-049)
* :class:`~dhc.event_stream.CompletionDispatcher` — at-most-once (INFO-046)
* :class:`~dhc.artifact_store.ArtifactStore` — content-addressed (INFO-006)
* the communication channels (Messenger, RoomManager, EscalationChannel,
  OperatorQuestionChannel) on the same bus
* the in-code namespace extensions (publish-with-event, messenger, room,
  escalate, ask_operator, MockDriver, driver_from_settings)
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Optional

from .artifact_store import ArtifactStore, BoundaryEventLog
from .communication import (
    EscalationChannel,
    Messenger,
    OperatorQuestionChannel,
    RoomManager,
)
from .config import get_settings
from .driver import MockDriver, driver_from_settings
from .errors import ChannelError, TurnError, TurnTimeoutError
from .event_stream import CompletionDispatcher, EventBus
from .models import Artifact, Event, EventKind, Message
from .operator import Operator
from .repl import ReplEngine
from .runtime import Runtime

#: Map the runtime's event kinds onto the five boundary kinds (INFO-049).
_BOUNDARY_KIND = {
    EventKind.child_spawned: "spawned",
    EventKind.child_settled: "settled",
    EventKind.cancelled: "cancelled",
    EventKind.artifact_published: "published",
    EventKind.message_sent: "messaged",
    EventKind.room_message: "messaged",
}


class _BoundarySink:
    """Adapt the bus/messenger sinks to the BoundaryEventLog (INFO-049).

    The bus calls ``sink.append(event)`` with a :class:`~dhc.models.Event`;
    the Messenger calls ``sink.append(message)`` with a
    :class:`~dhc.models.Message`; the RoomManager calls
    ``sink.append(("room_message", room_name, message))``. This sink
    translates each into a boundary-log record, mapping the runtime's event
    kinds onto the five boundary kinds (spawned/settled/cancelled/published/
    messaged) and linking settled/published records to their causal spawned
    record via ``causal_id`` so the trail reconstructs as a DAG.
    """

    def __init__(self, log: BoundaryEventLog) -> None:
        self._log = log
        #: child_id -> causal id of the spawned record that created it.
        self._spawned: dict[str, str] = {}
        self._lock = threading.Lock()

    def append(self, obj: Any) -> None:
        if isinstance(obj, Event):
            self._append_event(obj)
        elif isinstance(obj, Message):
            self._append_message(obj)
        elif (
            isinstance(obj, tuple)
            and len(obj) == 3
            and obj[0] == "room_message"
        ):
            _, room_name, message = obj
            self._append_room(room_name, message)

    def _append_event(self, event: Event) -> None:
        kind = _BOUNDARY_KIND.get(event.kind)
        if kind is None:
            return  # not a boundary crossing (turn_*, crash, escalation, ...)
        causal_id = event.causal_id
        if kind == "spawned":
            child_id = event.payload.get("child_id")
            causal_id = f"spawned:{event.agent_id}:{child_id}"
            with self._lock:
                self._spawned[child_id] = causal_id
        elif kind in ("settled", "published"):
            with self._lock:
                causal_id = self._spawned.get(event.agent_id)
        with self._lock:
            self._log.append(
                kind, event.agent_id, causal_id=causal_id, payload=event.payload
            )

    def _append_message(self, message: Message) -> None:
        with self._lock:
            self._log.append(
                "messaged",
                message.sender_id,
                causal_id=None,
                payload={
                    "recipient_id": message.recipient_id,
                    "body": message.body,
                },
            )

    def _append_room(self, room_name: str, message: Message) -> None:
        with self._lock:
            self._log.append(
                "messaged",
                message.sender_id,
                causal_id=None,
                payload={"room": room_name, "body": message.body},
            )


class _WiredBus:
    """Present the runtime's topic-based bus contract over the real modules.

    The committed runtime calls ``publish(topic, event)`` and ``drain(topic)``
    with topics ``events:<agent_id>`` and ``completions:<agent_id>``. This
    adapter routes:

    * ``events:*`` -> the real :class:`~dhc.event_stream.EventBus` (which
      persists to the boundary log via its sink, then routes to the agent's
      stream).
    * ``completions:*`` -> the real
      :class:`~dhc.event_stream.CompletionDispatcher` (at-most-once, FIFO per
      parent).
    """

    def __init__(self, bus: EventBus, dispatcher: CompletionDispatcher) -> None:
        self._bus = bus
        self._dispatcher = dispatcher

    def publish(self, topic: str, event: Any) -> None:
        if topic.startswith("events:"):
            self._bus.publish(event)
        elif topic.startswith("completions:"):
            parent_id = topic[len("completions:") :]
            self._dispatcher.enqueue(event, parent_id=parent_id)
        else:
            raise ValueError(f"unknown bus topic {topic!r}")

    def drain(self, topic: str) -> list:
        if topic.startswith("events:"):
            agent_id = topic[len("events:") :]
            return self._bus.stream_for(agent_id).drain()
        if topic.startswith("completions:"):
            agent_id = topic[len("completions:") :]
            return self._dispatcher.drain_for(agent_id)
        raise ValueError(f"unknown bus topic {topic!r}")


class _ReplEngineAdapter:
    """Translate the ReplEngine's Result-returning contract into the
    runtime's raising contract.

    The committed runtime catches ``TurnTimeoutError`` (-> timeout terminal)
    and ``Exception`` (-> failed terminal) from ``engine.execute``. The real
    ReplEngine never raises: it returns a failed :class:`~dhc.models.Result`
    both when the code raised (contained, INFO-005) and when the agent
    deliberately called ``fail()``. This adapter re-raises only the former —
    a deliberate ``fail()`` leaves ``agent._last_result`` set, which the
    runtime reads and settles on; a raised exception leaves it ``None``, so
    the runtime's crash containment must see it.
    """

    def __init__(
        self,
        engine: ReplEngine,
        resolve_agent: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._engine = engine
        self._resolve_agent = resolve_agent

    def execute(
        self,
        agent_id: str,
        code: str,
        namespace: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        result = self._engine.execute(agent_id, code, namespace, timeout)
        if result.ok:
            return result
        reason = result.reason or "turn failed"
        if "timed out" in reason:
            raise TurnTimeoutError(reason)
        agent = self._resolve_agent(agent_id) if self._resolve_agent else None
        if agent is not None and agent._last_result is not None:
            # The agent deliberately produced a result (complete/fail/cancel);
            # the runtime reads agent._last_result and settles accordingly.
            return result
        raise TurnError(reason)


class _StoreAdapter:
    """Adapt the ArtifactStore to the in-code ``publish(h, s, r)`` contract.

    The in-code surface calls ``store.publish(headline, summary, report)``
    (contract §1); the real :class:`~dhc.artifact_store.ArtifactStore` has
    ``put(artifact)``. This adapter builds the content-addressed
    :class:`~dhc.models.Artifact` and stores it, then exposes the read tiers
    for consumers (progressive disclosure, INFO-006).
    """

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def publish(self, headline: str, summary: str, report: Any) -> Artifact:
        artifact = Artifact(headline=headline, summary=summary, report=report)
        self._store.put(artifact)
        return artifact

    def get(self, artifact_id: str) -> Artifact:
        return self._store.get(artifact_id)

    def exists(self, artifact_id: str) -> bool:
        return self._store.exists(artifact_id)

    def get_headline(self, artifact_id: str) -> str:
        return self._store.get_headline(artifact_id)

    def get_summary(self, artifact_id: str) -> str:
        return self._store.get_summary(artifact_id)

    def get_report(self, artifact_id: str) -> object:
        return self._store.get_report(artifact_id)

    def list_ids(self) -> list:
        return self._store.list_ids()

    def count(self) -> int:
        return self._store.count()


class _BoundMessenger:
    """A per-agent facade over the shared Messenger (INFO-015)."""

    def __init__(self, messenger: Messenger, agent_id: str) -> None:
        self._messenger = messenger
        self._agent_id = agent_id

    def send(self, recipient_id: str, body: str) -> Message:
        return self._messenger.send(self._agent_id, recipient_id, body)

    def inbox(self) -> list:
        return self._messenger.inbox(self._agent_id)

    def unread_count(self) -> int:
        return self._messenger.unread_count(self._agent_id)


def _publish_with_event(agent: Any, bus: EventBus) -> Any:
    """Wrap ``publish`` so every artifact crossing the boundary is logged."""

    def publish(headline: str, summary: str, report: Any) -> Artifact:
        artifact = agent.publish(headline, summary, report)
        bus.publish(
            Event(
                kind=EventKind.artifact_published,
                agent_id=agent.id,
                payload={"artifact_id": artifact.id},
            )
        )
        return artifact

    return publish


def _escalate(escalations: EscalationChannel, agent: Any) -> Any:
    """Bind the escalation channel to *agent* (INFO-011, upstream only)."""

    def escalate(reason: str) -> Event:
        if agent.parent_id is None:
            raise ChannelError("root agent has no parent to escalate to")
        return escalations.escalate(
            agent.id, agent.parent_id, agent.requirement, reason
        )

    return escalate


def _extend_namespace(
    runtime: Runtime,
    bus: EventBus,
    messenger: Messenger,
    rooms: RoomManager,
    escalations: EscalationChannel,
    questions: OperatorQuestionChannel,
) -> None:
    """Extend the runtime's in-code namespace with the wired surface.

    The committed :class:`~dhc.runtime.Runtime` builds the base namespace
    (agent, publish, spawn, complete, fail, cancel, status, result, tool,
    bash, room, await_, poll, children_of). This wraps that builder to add
    the real channel helpers and the driver factory, so action blocks can use
    the full surface.
    """
    original = runtime._build_namespace

    def build(agent: Any) -> dict:
        ns = original(agent)
        ns["publish"] = _publish_with_event(agent, bus)
        ns["room"] = lambda name: rooms.join(agent.id, name)
        ns["messenger"] = _BoundMessenger(messenger, agent.id)
        ns["escalate"] = _escalate(escalations, agent)
        ns["ask_operator"] = lambda question: questions.ask(agent.id, question)
        ns["MockDriver"] = MockDriver
        ns["driver_from_settings"] = driver_from_settings
        return ns

    runtime._build_namespace = build  # type: ignore[method-assign]


def build_runtime(
    settings: Any = None,
    mock: bool = False,
    artifact_root: Any = None,
) -> Runtime:
    """Construct a fully-wired :class:`~dhc.runtime.Runtime`.

    Wires the REAL modules: ReplEngine, EventBus (with BoundaryEventLog as
    the persist sink), CompletionDispatcher, ArtifactStore, and the
    communication channels (Messenger, RoomManager, EscalationChannel,
    OperatorQuestionChannel) — all on the same bus. The channels are exposed
    as ``runtime.messenger``, ``runtime.rooms``, ``runtime.escalations``,
    ``runtime.questions``; the operator door as ``runtime.operator``; the
    dispatcher as ``runtime.dispatcher``; the boundary log as
    ``runtime.boundary_log``.

    *settings* defaults to the process-wide :func:`~dhc.config.get_settings`.
    *artifact_root* overrides the store/log location (tests pass a tmp dir).
    *mock* is recorded on the runtime (``runtime.mock``) and used by
    :func:`~dhc.driver.driver_from_settings` when callers build drivers.
    """
    if settings is None:
        settings = get_settings()
    root = (
        Path(artifact_root)
        if artifact_root is not None
        else Path(settings.artifact_root)
    )
    store = ArtifactStore(root)
    boundary_log = BoundaryEventLog(root)
    sink = _BoundarySink(boundary_log)
    bus = EventBus(sink=sink)
    dispatcher = CompletionDispatcher()
    store_adapter = _StoreAdapter(store)

    runtime = Runtime(
        engine=None,  # wired below (needs the runtime for agent resolution)
        event_bus=_WiredBus(bus, dispatcher),
        artifact_store=store_adapter,
        settings=settings,
    )
    engine = _ReplEngineAdapter(
        ReplEngine(), resolve_agent=runtime._agents.__getitem__
    )
    runtime.engine = engine

    messenger = Messenger(bus, registry=runtime._agents, sink=sink)
    rooms = RoomManager(bus, sink=sink)
    escalations = EscalationChannel(bus)
    questions = OperatorQuestionChannel(bus)

    runtime.messenger = messenger
    runtime.rooms = rooms
    runtime.escalations = escalations
    runtime.questions = questions
    runtime.dispatcher = dispatcher
    runtime.boundary_log = boundary_log
    runtime.bus = bus
    runtime.artifact_store_real = store
    runtime.operator = Operator(runtime=runtime, question_channel=questions)
    runtime.mock = mock

    _extend_namespace(runtime, bus, messenger, rooms, escalations, questions)
    return runtime