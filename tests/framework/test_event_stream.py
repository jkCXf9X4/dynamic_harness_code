"""Tests for dhc.event_stream: EventStream, EventBus, CompletionDispatcher.

Covers the INFO-046/047/048/051 semantics: persist-before-execute,
at-most-once delivery and settlement, serialized callbacks, FIFO completion
order per parent, and EventBus routing.
"""

import threading
import time
from datetime import datetime, timezone

import pytest

from dhc.errors import ChannelError
from dhc.framework.event_stream import CompletionDispatcher, EventBus, EventStream
from dhc.data.models import AgentStatus, Completion, Event, EventKind


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
# EventStream: register / emit / drain
# --------------------------------------------------------------------------- #


def test_register_emit_delivers_to_callback():
    stream = EventStream()
    received = []
    stream.register(received.append)
    event = _event()
    stream.emit(event)
    assert received == [event]


def test_emit_delivers_to_all_registered_callbacks_in_order():
    stream = EventStream()
    order = []
    stream.register(lambda e: order.append(("first", e)))
    stream.register(lambda e: order.append(("second", e)))
    event = _event()
    stream.emit(event)
    assert order == [("first", event), ("second", event)]


def test_emit_delivers_events_in_fifo_order():
    stream = EventStream()
    received = []
    stream.register(received.append)
    e1, e2, e3 = _event(kind=EventKind.turn_started), _event(), _event(kind=EventKind.cancelled)
    stream.emit(e1)
    stream.emit(e2)
    stream.emit(e3)
    assert received == [e1, e2, e3]


def test_drain_consumes_pending_in_order():
    stream = EventStream()
    e1, e2 = _event(), _event(kind=EventKind.cancelled)
    stream.emit(e1)
    stream.emit(e2)
    assert stream.pending_count() == 2
    assert stream.drain() == [e1, e2]
    assert stream.pending_count() == 0
    assert stream.drain() == []


def test_pending_count_tracks_undrained_events():
    stream = EventStream()
    assert stream.pending_count() == 0
    stream.emit(_event())
    stream.emit(_event())
    assert stream.pending_count() == 2
    stream.drain()
    assert stream.pending_count() == 0


# --------------------------------------------------------------------------- #
# EventStream: at-most-once
# --------------------------------------------------------------------------- #


def test_registering_same_callback_twice_delivers_once():
    stream = EventStream()
    received = []
    stream.register(received.append)
    stream.register(received.append)
    stream.emit(_event())
    assert len(received) == 1


def test_emitting_same_event_twice_delivers_once():
    stream = EventStream()
    received = []
    stream.register(received.append)
    event = _event()
    stream.emit(event)
    stream.emit(event)
    assert received == [event]
    assert stream.pending_count() == 1


def test_distinct_events_deliver_even_if_equal():
    stream = EventStream()
    received = []
    stream.register(received.append)
    e1 = _event()
    e2 = _event()
    stream.emit(e1)
    stream.emit(e2)
    assert received == [e1, e2]


# --------------------------------------------------------------------------- #
# EventStream: persist-before-execute
# --------------------------------------------------------------------------- #


def test_emit_persists_to_sink_before_callbacks():
    sink = _Sink()
    stream = EventStream(sink=sink)
    seen = []

    def callback(event):
        # The event must already be in the sink when the callback runs.
        seen.append((event, list(sink.events)))

    stream.register(callback)
    event = _event()
    stream.emit(event)
    assert seen == [(event, [event])]
    assert sink.events == [event]


def test_raising_callback_does_not_propagate_and_event_stays_persisted():
    sink = _Sink()
    stream = EventStream(sink=sink)
    calls = []

    def boom(event):
        calls.append(event)
        raise RuntimeError("callback exploded")

    stream.register(boom)
    event = _event()
    stream.emit(event)  # must not raise
    assert calls == [event]
    assert sink.events == [event]
    assert stream.pending_count() == 1


def test_raising_callback_does_not_block_later_callbacks():
    stream = EventStream()
    order = []

    def boom(event):
        order.append("boom")
        raise RuntimeError("boom")

    def after(event):
        order.append("after")

    stream.register(boom)
    stream.register(after)
    stream.emit(_event())
    assert order == ["boom", "after"]


def test_emit_without_sink_is_noop_persistence():
    stream = EventStream()
    received = []
    stream.register(received.append)
    event = _event()
    stream.emit(event)
    assert received == [event]


# --------------------------------------------------------------------------- #
# EventStream: serialized callbacks
# --------------------------------------------------------------------------- #


def test_callbacks_never_run_concurrently():
    stream = EventStream()
    active = 0
    max_active = 0
    lock = threading.Lock()

    def slow_callback(event):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.05)
        with lock:
            active -= 1

    stream.register(slow_callback)
    stream.register(slow_callback)

    threads = [threading.Thread(target=stream.emit, args=(_event(),)) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert max_active == 1
    assert stream.pending_count() == 4


# --------------------------------------------------------------------------- #
# EventBus: routing
# --------------------------------------------------------------------------- #


def test_publish_routes_to_per_agent_stream():
    bus = EventBus()
    received = []
    bus.subscribe("a1", received.append)
    event = _event(agent_id="a1")
    bus.publish(event)
    assert received == [event]


def test_publish_routes_to_global_listeners():
    bus = EventBus()
    received = []
    bus.subscribe_global(received.append)
    event = _event(agent_id="a1")
    bus.publish(event)
    assert received == [event]


def test_publish_routes_to_both_stream_and_globals():
    bus = EventBus()
    stream_received = []
    global_received = []
    bus.subscribe("a1", stream_received.append)
    bus.subscribe_global(global_received.append)
    event = _event(agent_id="a1")
    bus.publish(event)
    assert stream_received == [event]
    assert global_received == [event]


def test_publish_does_not_route_to_other_agents_stream():
    bus = EventBus()
    received = []
    bus.subscribe("a2", received.append)
    bus.publish(_event(agent_id="a1"))
    assert received == []


def test_stream_for_returns_same_stream_per_agent():
    bus = EventBus()
    assert bus.stream_for("a1") is bus.stream_for("a1")
    assert bus.stream_for("a1") is not bus.stream_for("a2")


def test_publish_persists_once_to_sink_before_routing():
    sink = _Sink()
    bus = EventBus(sink=sink)
    stream_received = []
    global_received = []
    bus.subscribe("a1", stream_received.append)
    bus.subscribe_global(global_received.append)
    event = _event(agent_id="a1")
    bus.publish(event)
    assert sink.events == [event]
    assert stream_received == [event]
    assert global_received == [event]


def test_publish_without_sink_is_noop_persistence():
    bus = EventBus()
    received = []
    bus.subscribe_global(received.append)
    event = _event()
    bus.publish(event)
    assert received == [event]


def test_raising_global_listener_does_not_propagate():
    bus = EventBus()
    order = []

    def boom(event):
        order.append("boom")
        raise RuntimeError("boom")

    def after(event):
        order.append("after")

    bus.subscribe_global(boom)
    bus.subscribe_global(after)
    bus.publish(_event())
    assert order == ["boom", "after"]


# --------------------------------------------------------------------------- #
# CompletionDispatcher: FIFO per parent, at-most-once, drain
# --------------------------------------------------------------------------- #


def test_next_for_returns_completions_in_fifo_order():
    dispatcher = CompletionDispatcher()
    c1 = _completion(agent_id="child1", summary="first")
    c2 = _completion(agent_id="child2", summary="second")
    c3 = _completion(agent_id="child3", summary="third")
    dispatcher.enqueue(c1, parent_id="parent")
    dispatcher.enqueue(c2, parent_id="parent")
    dispatcher.enqueue(c3, parent_id="parent")
    assert dispatcher.next_for("parent") is c1
    assert dispatcher.next_for("parent") is c2
    assert dispatcher.next_for("parent") is c3
    assert dispatcher.next_for("parent") is None


def test_completion_order_is_per_parent():
    dispatcher = CompletionDispatcher()
    c1 = _completion(agent_id="child1", summary="p1-first")
    c2 = _completion(agent_id="child2", summary="p2-first")
    c3 = _completion(agent_id="child3", summary="p1-second")
    dispatcher.enqueue(c1, parent_id="p1")
    dispatcher.enqueue(c2, parent_id="p2")
    dispatcher.enqueue(c3, parent_id="p1")
    assert dispatcher.next_for("p1") is c1
    assert dispatcher.next_for("p1") is c3
    assert dispatcher.next_for("p1") is None
    assert dispatcher.next_for("p2") is c2
    assert dispatcher.next_for("p2") is None


def test_has_pending_reflects_queue_state():
    dispatcher = CompletionDispatcher()
    assert not dispatcher.has_pending("parent")
    dispatcher.enqueue(_completion(agent_id="child1"), parent_id="parent")
    assert dispatcher.has_pending("parent")
    dispatcher.next_for("parent")
    assert not dispatcher.has_pending("parent")


def test_drain_for_returns_all_in_fifo_order():
    dispatcher = CompletionDispatcher()
    c1 = _completion(agent_id="child1", summary="first")
    c2 = _completion(agent_id="child2", summary="second")
    dispatcher.enqueue(c1, parent_id="parent")
    dispatcher.enqueue(c2, parent_id="parent")
    assert dispatcher.drain_for("parent") == [c1, c2]
    assert dispatcher.drain_for("parent") == []
    assert not dispatcher.has_pending("parent")


def test_double_settle_raises_channel_error():
    dispatcher = CompletionDispatcher()
    dispatcher.enqueue(_completion(agent_id="child1"), parent_id="parent")
    with pytest.raises(ChannelError):
        dispatcher.enqueue(_completion(agent_id="child1"), parent_id="parent")


def test_double_settle_raises_even_for_different_parents():
    dispatcher = CompletionDispatcher()
    dispatcher.enqueue(_completion(agent_id="child1"), parent_id="p1")
    with pytest.raises(ChannelError):
        dispatcher.enqueue(_completion(agent_id="child1"), parent_id="p2")


def test_enqueue_defaults_parent_to_completion_agent_id():
    dispatcher = CompletionDispatcher()
    c = _completion(agent_id="child1")
    dispatcher.enqueue(c)
    assert dispatcher.next_for("child1") is c


def test_distinct_children_can_each_settle_once():
    dispatcher = CompletionDispatcher()
    dispatcher.enqueue(_completion(agent_id="child1"), parent_id="parent")
    dispatcher.enqueue(_completion(agent_id="child2"), parent_id="parent")
    assert dispatcher.has_pending("parent")
    drained = dispatcher.drain_for("parent")
    assert [c.agent_id for c in drained] == ["child1", "child2"]