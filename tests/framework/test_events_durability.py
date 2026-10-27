"""Mesh-survival guarantees for events and completions.

Two guarantees used to be in-memory only:

* at-most-once event delivery keyed on ``id(event)`` object identity, so a
  reconstructed but equivalent event double-delivered;
* the :class:`CompletionDispatcher` had no sink, so pending child settlements
  were lost on restart.

These tests cover the replacements: a stable ``Event.event_id`` minted at
construction is the dedup key, and the dispatcher persists settlements
(write-before-ack) into the artifact store so a fresh dispatcher over the same
store replays each undelivered settlement exactly once.
"""

import pytest

from dhc.data.models import AgentStatus, Completion, Event, EventKind
from dhc.framework.event_stream import CompletionDispatcher, EventBus, EventStream
from dhc.errors import ChannelError
from dhc.tooling import ArtifactStore
from dhc.wiring import build_runtime

pytestmark = pytest.mark.slow


def _event(agent_id: str = "a1", kind: EventKind = EventKind.turn_completed) -> Event:
    return Event(kind=kind, agent_id=agent_id)


def _completion(
    agent_id: str = "child1",
    status: AgentStatus = AgentStatus.completed,
    summary: str = "done",
) -> Completion:
    return Completion(agent_id=agent_id, status=status, summary=summary)


class _Sink:
    """Recording sink: duck-typed ``append(event)``."""

    def __init__(self) -> None:
        self.events: list[Event] = []

    def append(self, event: Event) -> None:
        self.events.append(event)


# --------------------------------------------------------------------------- #
# Stable event identity
# --------------------------------------------------------------------------- #


def test_event_carries_a_stable_id_minted_at_construction():
    first, second = _event(), _event()
    assert first.event_id
    assert second.event_id
    assert first.event_id != second.event_id


def test_event_id_survives_serialization_round_trip():
    event = _event()
    rebuilt = Event(**event.model_dump())
    assert rebuilt.event_id == event.event_id


def test_same_object_emitted_twice_delivers_once():
    stream = EventStream()
    received = []
    stream.register(received.append)
    event = _event()
    stream.emit(event)
    stream.emit(event)
    assert received == [event]
    assert stream.pending_count() == 1


def test_reconstructed_equivalent_event_delivers_once():
    """The old ``id(event)`` key double-delivered this; ``event_id`` does not."""
    stream = EventStream()
    received = []
    stream.register(received.append)
    event = _event()
    rebuilt = Event(**event.model_dump())
    assert rebuilt is not event
    assert stream.emit(event) is True
    assert stream.emit(rebuilt) is False
    assert received == [event]
    assert stream.pending_count() == 1


def test_distinct_events_with_identical_content_both_deliver():
    """The id is minted per event, not derived from content: no over-dedup."""
    stream = EventStream()
    received = []
    stream.register(received.append)
    first, second = _event(), _event()
    same_fields = first.model_dump(exclude={"event_id", "ts"}) == second.model_dump(
        exclude={"event_id", "ts"}
    )
    assert same_fields
    stream.emit(first)
    stream.emit(second)
    assert received == [first, second]


def test_bus_does_not_re_persist_a_duplicate_event():
    sink = _Sink()
    bus = EventBus(sink=sink)
    received = []
    bus.subscribe("a1", received.append)
    event = _event(agent_id="a1")
    bus.publish(event)
    bus.publish(Event(**event.model_dump()))
    assert sink.events == [event]
    assert received == [event]
    assert bus.stream_for("a1").pending_count() == 1


# --------------------------------------------------------------------------- #
# CompletionDispatcher: no sink -> behaviour unchanged
# --------------------------------------------------------------------------- #


def test_dispatcher_without_sink_is_unchanged():
    dispatcher = CompletionDispatcher()
    assert dispatcher.durable is False
    c1, c2 = _completion("child1", summary="first"), _completion("child2")
    dispatcher.enqueue(c1, parent_id="parent")
    dispatcher.enqueue(c2, parent_id="parent")
    assert dispatcher.next_for("parent") is c1
    assert dispatcher.drain_for("parent") == [c2]
    assert dispatcher.drain_for("parent") == []
    with pytest.raises(ChannelError):
        dispatcher.enqueue(c1, parent_id="parent")


# --------------------------------------------------------------------------- #
# CompletionDispatcher: durable sink
# --------------------------------------------------------------------------- #


def _store(tmp_path) -> ArtifactStore:
    return ArtifactStore(tmp_path)


def _records(store: ArtifactStore, marker: str) -> list[dict]:
    return [
        report
        for artifact_id in store.list_ids()
        for report in [store.get_report(artifact_id)]
        if isinstance(report, dict) and report.get("record") == marker
    ]


def test_enqueue_persists_the_settlement_before_it_is_queued(tmp_path):
    store = _store(tmp_path)
    dispatcher = CompletionDispatcher(sink=store)
    assert dispatcher.durable is True
    dispatcher.enqueue(_completion(), parent_id="parent")

    settlements = _records(store, CompletionDispatcher.SETTLEMENT_RECORD)
    assert len(settlements) == 1
    assert settlements[0]["parent_id"] == "parent"
    assert settlements[0]["completion"]["agent_id"] == "child1"


def test_settlement_is_not_acknowledged_until_it_is_delivered(tmp_path):
    store = _store(tmp_path)
    dispatcher = CompletionDispatcher(sink=store)
    dispatcher.enqueue(_completion(), parent_id="parent")
    assert _records(store, CompletionDispatcher.DELIVERY_RECORD) == []

    dispatcher.next_for("parent")
    assert len(_records(store, CompletionDispatcher.DELIVERY_RECORD)) == 1


def test_fresh_dispatcher_replays_undelivered_settlement_once(tmp_path):
    store = _store(tmp_path)
    settlement = _completion()
    CompletionDispatcher(sink=store).enqueue(settlement, parent_id="parent")

    recovered = CompletionDispatcher(sink=store)
    assert recovered.drain_for("parent") == [settlement]
    # A third dispatcher sees the delivery acknowledgement: no second delivery.
    assert CompletionDispatcher(sink=store).drain_for("parent") == []


def test_delivered_settlement_is_not_replayed(tmp_path):
    store = _store(tmp_path)
    first = CompletionDispatcher(sink=store)
    first.enqueue(_completion(), parent_id="parent")
    assert len(first.drain_for("parent")) == 1

    assert CompletionDispatcher(sink=store).drain_for("parent") == []


def test_replay_preserves_completion_order(tmp_path):
    store = _store(tmp_path)
    first = CompletionDispatcher(sink=store)
    settled = [_completion(f"child{i}", summary=f"s{i}") for i in range(1, 4)]
    for completion in settled:
        first.enqueue(completion, parent_id="parent")

    replayed = CompletionDispatcher(sink=store).drain_for("parent")
    assert [c.agent_id for c in replayed] == ["child1", "child2", "child3"]


def test_replay_restores_at_most_once(tmp_path):
    store = _store(tmp_path)
    completion = _completion()
    CompletionDispatcher(sink=store).enqueue(completion, parent_id="parent")

    recovered = CompletionDispatcher(sink=store)
    with pytest.raises(ChannelError):
        recovered.enqueue(completion, parent_id="parent")


def test_replay_delivers_each_pending_settlement_exactly_once(tmp_path):
    store = _store(tmp_path)
    first = CompletionDispatcher(sink=store)
    delivered = _completion("child1")
    pending = _completion("child2")
    first.enqueue(delivered, parent_id="parent")
    first.enqueue(pending, parent_id="parent")
    assert first.next_for("parent") == delivered  # acked, no longer pending

    recovered = CompletionDispatcher(sink=store)
    assert recovered.drain_for("parent") == [pending]
    # Once delivered, later restarts must not deliver the survivor again.
    for _ in range(2):
        assert CompletionDispatcher(sink=store).drain_for("parent") == []


def test_build_runtime_wires_the_durable_dispatcher(tmp_path):
    runtime = build_runtime(mock=True, artifact_root=tmp_path)
    try:
        assert runtime.dispatcher.durable is True
        settlement = _completion()
        runtime.dispatcher.enqueue(settlement, parent_id="parent")

        # The same store the composition root wired is the replay source.
        recovered = CompletionDispatcher(sink=runtime.artifact_store)
        assert recovered.drain_for("parent") == [settlement]
        assert (
            CompletionDispatcher(sink=runtime.artifact_store).drain_for("parent")
            == []
        )
    finally:
        runtime.stop()
