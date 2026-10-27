"""Event stream, event bus, and completion dispatcher for dhc.

Implements the runtime-owned event resolution semantics:

- **INFO-048 persist-before-execute**: an event is written to the sink *before*
  any callback runs; a raising callback never propagates to the emitter and
  never loses the event.
- **INFO-046 at-most-once**: one settled child = one completion; settlement is
  gated by :class:`~dhc.models.CompletionLog` (double-settle raises
  :class:`~dhc.errors.ChannelError`); an event is delivered to a given
  callback at most once, keyed by the event's stable ``event_id``.
- **INFO-047 completion ordering**: completions queue per parent and are
  consumed FIFO, in completion order, between the parent's own actions.
- **INFO-051 runtime-owned surface**: agent code only registers callbacks; the
  stream surface (``drain``/``pending_count``) belongs to the runtime's event
  loop, never to agent code.

The sink is duck-typed (``sink.append(event)``) so the operator-side
``dhc.tooling.BoundaryEventLog`` can be wired in by the composition root;
``None`` means no-op persistence. The core only ever sees events — which
persistence they end up in is a tooling concern (decision 0014).

The :class:`CompletionDispatcher` takes an optional *settlement sink* — the
same artifact store the composition root wires elsewhere. With a sink, a
settlement is written (content-addressed, hence idempotent) before it is
acknowledged, and delivery writes an acknowledgement record, so a fresh
dispatcher built over the same sink never delivers a persisted settlement
twice.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Callable, Optional

from ..data.models import Artifact, Completion, CompletionLog, Event


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
        # event_id -> event; holds a reference so the stable id cannot be
        # recycled and at-most-once holds for the lifetime of the stream.
        self._seen: dict[str, Event] = {}
        self._lock = threading.RLock()

    def register(self, callback: Callable[[Event], None]) -> None:
        """Register *callback*; registering the same callback twice is a no-op."""
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def seen(self, event_id: str) -> bool:
        """True when an event with *event_id* was already emitted here."""
        with self._lock:
            return event_id in self._seen

    def emit(self, event: Event) -> bool:
        """Persist *event* to the sink, then deliver it to every callback.

        At-most-once keys on the event's stable ``event_id``: emitting the
        same event again — or an equivalent event reconstructed from its
        serialized form — is a no-op (returns ``False``). Callback errors are
        contained and never propagate to the emitter. A sink failure
        propagates: persistence is the durability guarantee, so a failed
        append aborts the emit.
        """
        with self._lock:
            if event.event_id in self._seen:
                return False
            self._seen[event.event_id] = event
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
            return True

    def drain(self) -> list[Event]:
        """Consume and return all pending events, in emit order."""
        with self._lock:
            pending = self._pending
            self._pending = []
            return pending

    def peek(self) -> list[Event]:
        """Return the pending events without consuming them (fan-out seam).

        Drain-race fix: consumers of the ``events:<id>`` topics read
        through this non-destructive peek and keep their own cursor, so no
        consumer steals another's events. ``drain`` stays destructive (the
        runtime's poll surface, INFO-051).
        """
        with self._lock:
            return list(self._pending)

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

        At-most-once keys on the event's stable ``event_id``, checked before
        the sink write: a duplicate publish is neither re-persisted nor
        re-delivered. Callback errors are contained and never propagate to
        the publisher.
        """
        with self._lock:
            stream = self.stream_for(event.agent_id)
            if stream.seen(event.event_id):
                return
            if self._sink is not None:
                self._sink.append(event)
            stream.emit(event)
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

    Durability (optional *sink*): pass the composition root's artifact store
    (anything exposing the adapter-style ``publish(headline, summary,
    report)`` or the raw ``put(artifact)`` contract, plus ``list_ids()`` and
    ``get_report(id)`` for replay). With a sink:

    * a settlement is written *before* it is acknowledged (queued), so a
      crash after ``enqueue`` returns cannot lose it;
    * delivery writes an acknowledgement record *before* the completion is
      returned, so a settlement handed to a caller is never replayed;
    * a dispatcher built over the same sink replays exactly the settlements
      that were persisted but not acknowledged, in original completion order,
      and re-establishes the at-most-once gate from the log.

    Records are content-addressed artifacts, so re-writing one is idempotent.
    A write-only sink still gives persist-before-ack; replay needs the read
    side. ``sink=None`` (the default) keeps the original in-memory-only
    behaviour unchanged.
    """

    #: Report markers on the durable records written to the sink.
    SETTLEMENT_RECORD = "completion.settlement"
    DELIVERY_RECORD = "completion.delivery"

    def __init__(self, sink: Optional[object] = None) -> None:
        self._sink = sink
        self._log = CompletionLog()
        self._queues: dict[str, deque[Completion]] = {}
        #: child agent id -> id of its persisted settlement record.
        self._settlement_ids: dict[str, str] = {}
        self._seq = 0
        self._lock = threading.RLock()
        if sink is not None:
            self._replay()

    @property
    def durable(self) -> bool:
        """True when settlements are persisted through a sink."""
        return self._sink is not None

    # -- durable records -----------------------------------------------------

    def _write_record(
        self, headline: str, summary: str, report: dict
    ) -> str:
        """Persist one record through the sink; return its artifact id."""
        publish = getattr(self._sink, "publish", None)
        if callable(publish):
            return publish(headline, summary, report).id
        put = getattr(self._sink, "put", None)
        if not callable(put):
            raise TypeError(
                "completion sink must expose publish(headline, summary, "
                "report) or put(artifact), got "
                f"{type(self._sink).__name__!r}"
            )
        artifact = Artifact(headline=headline, summary=summary, report=report)
        put(artifact)
        return artifact.id

    def _persisted_records(self) -> list[tuple[str, dict]]:
        """Return ``(artifact_id, report)`` for every marked record in the sink."""
        list_ids = getattr(self._sink, "list_ids", None)
        get_report = getattr(self._sink, "get_report", None)
        if not (callable(list_ids) and callable(get_report)):
            return []  # write-only sink: persist-before-ack, no replay
        records: list[tuple[str, dict]] = []
        for artifact_id in list_ids():
            report = get_report(artifact_id)
            if isinstance(report, dict) and isinstance(report.get("record"), str):
                records.append((artifact_id, report))
        return records

    def _replay(self) -> None:
        """Reload persisted settlements/acknowledgements from the sink."""
        settlements: list[tuple[int, str, dict]] = []
        delivered: set[str] = set()
        for artifact_id, report in self._persisted_records():
            marker = report["record"]
            if marker == self.SETTLEMENT_RECORD:
                settlements.append(
                    (int(report.get("seq", 0)), artifact_id, report)
                )
            elif marker == self.DELIVERY_RECORD:
                delivered.add(str(report.get("settlement_id")))
        # Content addressing sorts by hash, not by write order: the recorded
        # sequence restores completion order (INFO-047).
        settlements.sort(key=lambda item: item[0])
        for seq, artifact_id, report in settlements:
            completion = Completion(**report["completion"])
            self._settlement_ids[completion.agent_id] = artifact_id
            self._seq = max(self._seq, seq)
            # At-most-once is rebuilt from the log, not from the queue.
            if completion.agent_id not in self._log:
                self._log.settle(completion)
            if artifact_id in delivered:
                continue
            parent_id = report.get("parent_id") or completion.agent_id
            self._queues.setdefault(parent_id, deque()).append(completion)

    def _ack_delivery(self, completion: Completion) -> None:
        """Write the delivery acknowledgement for *completion*, if any."""
        if self._sink is None:
            return
        settlement_id = self._settlement_ids.get(completion.agent_id)
        if settlement_id is None:
            return
        self._write_record(
            f"delivered: {completion.agent_id}",
            f"{completion.status.value} delivered to parent",
            {
                "record": self.DELIVERY_RECORD,
                "settlement_id": settlement_id,
            },
        )

    # -- queue surface -------------------------------------------------------

    def enqueue(
        self, completion: Completion, parent_id: Optional[str] = None
    ) -> None:
        """Queue *completion* for delivery to its parent.

        *parent_id* is the receiving parent; it defaults to
        ``completion.agent_id`` for callers that address completions to the
        parent directly. The runtime should pass the parent explicitly,
        because :class:`~dhc.models.Completion` records the settled *child*.
        Double-settling the same child raises ``ChannelError``.

        With a sink the settlement is written before the completion is
        queued (persist-before-ack); a failed write propagates and the
        completion is not queued.
        """
        with self._lock:
            self._log.settle(completion)
            key = parent_id if parent_id is not None else completion.agent_id
            if self._sink is not None:
                self._seq += 1
                self._settlement_ids[completion.agent_id] = self._write_record(
                    f"settlement: {completion.agent_id}",
                    f"{completion.status.value}: {completion.summary}",
                    {
                        "record": self.SETTLEMENT_RECORD,
                        "seq": self._seq,
                        "parent_id": key,
                        "completion": completion.model_dump(mode="json"),
                    },
                )
            self._queues.setdefault(key, deque()).append(completion)

    def next_for(self, agent_id: str) -> Optional[Completion]:
        """Pop and return the oldest pending completion for *agent_id*, or None."""
        with self._lock:
            queue = self._queues.get(agent_id)
            if not queue:
                return None
            completion = queue[0]
            self._ack_delivery(completion)  # durable before the caller sees it
            queue.popleft()
            return completion

    def drain_for(self, agent_id: str) -> list[Completion]:
        """Consume and return all pending completions for *agent_id*, FIFO."""
        with self._lock:
            queue = self._queues.get(agent_id)
            if not queue:
                return []
            completions = list(queue)
            for completion in completions:
                self._ack_delivery(completion)
            self._queues.pop(agent_id, None)
            return completions

    def has_pending(self, agent_id: str) -> bool:
        """True when *agent_id* has at least one undelivered completion."""
        with self._lock:
            queue = self._queues.get(agent_id)
            return bool(queue)