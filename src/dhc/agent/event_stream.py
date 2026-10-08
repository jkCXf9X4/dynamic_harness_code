"""Event stream, event bus, and completion dispatcher for dhc.

Implements the runtime-owned event resolution semantics:

- **INFO-048 persist-before-execute**: an event is written to the sink *before*
  any callback runs; a raising callback never propagates to the emitter and
  never loses the event.
- **INFO-046 at-most-once**: one settled child = one completion; settlement is
  gated by :class:`~dhc.models.CompletionLog` (double-settle raises
  :class:`~dhc.errors.ChannelError`); an event is delivered to a given
  callback at most once.
- **INFO-047 completion ordering**: completions queue per parent and are
  consumed FIFO, in completion order, between the parent's own actions.
- **INFO-051 runtime-owned surface**: agent code only registers callbacks; the
  stream surface (``drain``/``pending_count``) belongs to the runtime's event
  loop, never to agent code.

The sink is duck-typed (``sink.append(event)``) so the sibling
``artifact_store.BoundaryEventLog`` can be wired in later; ``None`` means
no-op persistence.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Callable, Optional

from ..data.models import Completion, CompletionLog, Event


class EventStream:
    """Per-agent event stream.

    ``emit`` persists the event to the sink *before* invoking callbacks
    (persist-before-execute), delivers each event to each registered callback
    at most once, and never runs callbacks concurrently. A callback that
    raises is contained: the event stays persisted and the error never
    propagates to the emitter.

    The pending queue (``drain``/``pending_count``) is the runtime's poll
    surface (INFO-048): the general event loop drains registered streams
    outside agent action code.
    """

    def __init__(self, sink: Optional[object] = None) -> None:
        self._sink = sink
        self._callbacks: list[Callable[[Event], None]] = []
        self._pending: list[Event] = []
        # id(event) -> event; holds a reference so ids cannot be recycled and
        # at-most-once holds for the lifetime of the stream.
        self._seen: dict[int, Event] = {}
        self._lock = threading.RLock()

    def register(self, callback: Callable[[Event], None]) -> None:
        """Register *callback*; registering the same callback twice is a no-op."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def emit(self, event: Event) -> None:
        """Persist *event* to the sink, then deliver it to every callback.

        At-most-once: emitting the same event object again is a no-op.
        Callback errors are contained and never propagate to the emitter.
        A sink failure propagates: persistence is the durability guarantee,
        so a failed append aborts the emit.
        """
        with self._lock:
            if id(event) in self._seen:
                return
            self._seen[id(event)] = event
            if self._sink is not None:
                self._sink.append(event)
            self._pending.append(event)
            for callback in self._callbacks:
                try:
                    callback(event)
                except Exception:
                    # Contained: the event is already persisted; the emitter
                    # must never see a callback failure (INFO-048).
                    pass

    def drain(self) -> list[Event]:
        """Consume and return all pending events, in emit order."""
        with self._lock:
            pending = self._pending
            self._pending = []
            return pending

    def pending_count(self) -> int:
        """Number of emitted events not yet drained."""
        with self._lock:
            return len(self._pending)


class EventBus:
    """Runtime-owned hub routing events to per-agent streams and global listeners.

    ``publish`` persists the event to the injected sink *once* (if any) before
    routing, so persist-before-execute holds for every subscriber. Streams
    created by the bus are sink-less: the bus is the single persistence point
    on the publish path, so the boundary log records each event exactly once.
    """

    def __init__(self, sink: Optional[object] = None) -> None:
        self._sink = sink
        self._streams: dict[str, EventStream] = {}
        self._globals: list[Callable[[Event], None]] = []
        self._lock = threading.RLock()

    def stream_for(self, agent_id: str) -> EventStream:
        """Return (creating if needed) the per-agent stream for *agent_id*."""
        with self._lock:
            stream = self._streams.get(agent_id)
            if stream is None:
                stream = EventStream()
                self._streams[agent_id] = stream
            return stream

    def subscribe(self, agent_id: str, callback: Callable[[Event], None]) -> None:
        """Register *callback* on the per-agent stream for *agent_id*."""
        self.stream_for(agent_id).register(callback)

    def subscribe_global(self, callback: Callable[[Event], None]) -> None:
        """Register *callback* to receive every published event."""
        with self._lock:
            if callback not in self._globals:
                self._globals.append(callback)

    def publish(self, event: Event) -> None:
        """Persist *event* (if a sink is set), then route it to the per-agent
        stream of ``event.agent_id`` and to every global listener.

        Callback errors are contained and never propagate to the publisher.
        """
        with self._lock:
            if self._sink is not None:
                self._sink.append(event)
            self.stream_for(event.agent_id).emit(event)
            for callback in self._globals:
                try:
                    callback(event)
                except Exception:
                    # Contained: never propagates to the publisher (INFO-048).
                    pass


class CompletionDispatcher:
    """Runtime-owned completion queue (INFO-047/048/046).

    One settled child = one completion, at most once: ``enqueue`` gates on
    :class:`~dhc.models.CompletionLog`, so a second settlement for the same
    child raises :class:`~dhc.errors.ChannelError`. Completions queue per
    parent and are consumed FIFO, in completion order, between the parent's
    own actions.
    """

    def __init__(self) -> None:
        self._log = CompletionLog()
        self._queues: dict[str, deque[Completion]] = {}
        self._lock = threading.RLock()

    def enqueue(
        self, completion: Completion, parent_id: Optional[str] = None
    ) -> None:
        """Queue *completion* for delivery to its parent.

        *parent_id* is the receiving parent; it defaults to
        ``completion.agent_id`` for callers that address completions to the
        parent directly. The runtime should pass the parent explicitly,
        because :class:`~dhc.models.Completion` records the settled *child*.
        Double-settling the same child raises ``ChannelError``.
        """
        with self._lock:
            self._log.settle(completion)
            key = parent_id if parent_id is not None else completion.agent_id
            self._queues.setdefault(key, deque()).append(completion)

    def next_for(self, agent_id: str) -> Optional[Completion]:
        """Pop and return the oldest pending completion for *agent_id*, or None."""
        with self._lock:
            queue = self._queues.get(agent_id)
            if not queue:
                return None
            return queue.popleft()

    def drain_for(self, agent_id: str) -> list[Completion]:
        """Consume and return all pending completions for *agent_id*, FIFO."""
        with self._lock:
            queue = self._queues.pop(agent_id, None)
            return list(queue) if queue else []

    def has_pending(self, agent_id: str) -> bool:
        """True when *agent_id* has at least one undelivered completion."""
        with self._lock:
            queue = self._queues.get(agent_id)
            return bool(queue)