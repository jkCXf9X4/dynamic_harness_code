"""Adapters: bridge the operator's artifact store onto the runtime seams.

Operator tooling (decision 0014): the framework core (``dhc.agent``) knows
artifacts only as opaque ids and the ``artifact_published`` event kind. These
adapters live on the tooling side of that line and are composed in by
``wiring.build_runtime``:

* :class:`StoreAdapter` — presents the raw ``ArtifactStore.put(artifact)``
  contract as the in-code ``publish(headline, summary, report)`` contract
  plus the progressive-disclosure read tiers (INFO-006).
* :class:`BoundarySink` — the event-bus persist sink: translates runtime
  events and room posts into the five boundary-log records (INFO-049),
  linking settled/published records to their causal spawned record via
  ``causal_id`` so the trail reconstructs as a DAG. Direct messages arrive
  as receiver-addressed ``message_sent`` events (decision 0015) — one event,
  one record, no separate message sink.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

from ..data.models import Artifact, Event, EventKind, Message
from .artifact_store import BoundaryEventLog

#: Map the runtime's event kinds onto the five boundary kinds (INFO-049).
_BOUNDARY_KIND = {
    EventKind.child_spawned: "spawned",
    EventKind.child_settled: "settled",
    EventKind.cancelled: "cancelled",
    EventKind.artifact_published: "published",
    EventKind.message_sent: "messaged",
    EventKind.room_message: "messaged",
}


class BoundarySink:
    """Adapt the bus/messenger sinks to the BoundaryEventLog (INFO-049).

    The bus calls ``sink.append(event)`` with a :class:`~dhc.models.Event`;
    the RoomManager calls ``sink.append(("room_message", room_name,
    message))``. This sink translates each into a boundary-log record,
    mapping the runtime's event kinds onto the five boundary kinds
    (spawned/settled/cancelled/published/messaged) and linking
    settled/published records to their causal spawned record via
    ``causal_id`` so the trail reconstructs as a DAG. Direct messages
    (decision 0015) arrive as receiver-addressed ``message_sent`` events
    on the bus itself — their body rides the event payload.
    """

    def __init__(self, log: BoundaryEventLog) -> None:
        self._log = log
        #: child_id -> causal id of the spawned record that created it.
        self._spawned: dict[str, str] = {}
        self._lock = threading.Lock()

    def append(self, obj: Any) -> None:
        if isinstance(obj, Event):
            self._append_event(obj)
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

    def _append_room(self, room_name: str, message: Message) -> None:
        with self._lock:
            self._log.append(
                "messaged",
                message.sender_id,
                causal_id=None,
                payload={"room": room_name, "body": message.body},
            )


class StoreAdapter:
    """Adapt the ArtifactStore to the in-code ``publish(h, s, r)`` contract.

    The in-code surface calls ``store.publish(headline, summary, report)``
    (contract §1); the raw :class:`~dhc.tooling.ArtifactStore` has
    ``put(artifact)``. This adapter builds the content-addressed
    :class:`~dhc.models.Artifact` and stores it, then exposes the read tiers
    for consumers (progressive disclosure, INFO-006).
    """

    def __init__(self, store: Any) -> None:
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

    def path_for(self, artifact_id: str) -> Path:
        """Return the on-disk path of the artifact's report body."""
        return self._store._report_path(artifact_id)
