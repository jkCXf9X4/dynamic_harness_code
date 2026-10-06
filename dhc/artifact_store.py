"""Immutable, content-addressed artifact store and boundary event log for dhc.

Artifacts (INFO-006) are the durable medium of the runtime: every finding,
result, and action's code persists as an immutable, content-addressed artifact.
Consumers pull progressive-disclosure tiers on demand — ``headline`` ->
``summary`` -> ``report`` — and handoffs between siblings are addressed by
content hash so they are safe to repeat and verify.

Storage layout under ``settings.artifact_root``::

    artifact_root/
        index.json                 # headline + summary per artifact id
        artifacts/<id>.json        # full report body per artifact
        boundary-events.jsonl      # append-only boundary event log (INFO-049)

The store is thread-safe (a single :class:`threading.Lock` guards all
mutations and the in-memory index) and survives reopen: the JSON index is
reloaded on construction. Stored artifacts are never mutated.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .errors import ArtifactNotFoundError
from .models import Artifact

#: The five boundary event kinds (INFO-049).
BOUNDARY_EVENT_KINDS: frozenset[str] = frozenset(
    {"spawned", "settled", "cancelled", "published", "messaged"}
)

_INDEX_NAME = "index.json"
_ARTIFACTS_DIR = "artifacts"
_BOUNDARY_LOG_NAME = "boundary-events.jsonl"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    """Serialize a datetime to a stable, sortable ISO-8601 string."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


class ArtifactStore:
    """Immutable, content-addressed artifact store persisted under a root dir.

    ``put`` dedupes by content hash: storing an artifact whose body is already
    present is idempotent and returns the existing id. Because the id *is* the
    sha256 content address, a different body can never collide with an existing
    id; if a caller nevertheless passes an artifact whose id maps to different
    content, ``put`` raises :class:`ValueError` (the id/body mismatch is also
    rejected by :class:`~dhc.models.Artifact` itself).
    """

    def __init__(self, artifact_root: Path) -> None:
        self._root = Path(artifact_root)
        self._artifacts_dir = self._root / _ARTIFACTS_DIR
        self._index_path = self._root / _INDEX_NAME
        self._lock = threading.Lock()
        #: id -> {"headline": str, "summary": str}
        self._index: dict[str, dict[str, str]] = {}
        self._load_index()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def put(self, artifact: Artifact) -> str:
        """Store *artifact* and return its content address (id).

        Idempotent for identical content: putting the same body twice returns
        the same id and does not duplicate storage. Raises
        :class:`ValueError` if the artifact's id maps to different content
        (defensive; :class:`~dhc.models.Artifact` already validates this).
        """
        if not isinstance(artifact, Artifact):
            raise TypeError(
                f"expected models.Artifact, got {type(artifact).__name__}"
            )
        aid = artifact.id
        with self._lock:
            # Defensive content-address verification: the id must be the
            # sha256 of the full body. models.Artifact already enforces this
            # on construction; this guards against forged/constructed
            # instances (e.g. via model_construct).
            computed = "sha256:" + hashlib.sha256(
                artifact.content().encode("utf-8")
            ).hexdigest()
            if aid != computed:
                raise ValueError(
                    f"artifact id {aid!r} does not match content hash "
                    f"{computed!r}"
                )
            existing = self._index.get(aid)
            if existing is not None:
                # Identical content already stored: idempotent. The id is the
                # content address, so a matching id implies a matching body;
                # the first write's headline/summary win.
                return aid
            self._artifacts_dir.mkdir(parents=True, exist_ok=True)
            self._write_report(aid, artifact.report)
            self._index[aid] = {
                "headline": artifact.headline,
                "summary": artifact.summary,
            }
            self._save_index()
            return aid

    def get(self, artifact_id: str) -> Artifact:
        """Return the stored artifact (headline, summary, full report)."""
        with self._lock:
            meta = self._index.get(artifact_id)
            if meta is None:
                raise ArtifactNotFoundError(
                    f"no artifact with id {artifact_id!r}"
                )
            report = self._read_report(artifact_id)
        return Artifact(
            id=artifact_id,
            headline=meta["headline"],
            summary=meta["summary"],
            report=report,
        )

    def get_headline(self, artifact_id: str) -> str:
        """Return the cheapest progressive-disclosure tier."""
        with self._lock:
            meta = self._index.get(artifact_id)
            if meta is None:
                raise ArtifactNotFoundError(
                    f"no artifact with id {artifact_id!r}"
                )
            return meta["headline"]

    def get_summary(self, artifact_id: str) -> str:
        """Return the middle progressive-disclosure tier."""
        with self._lock:
            meta = self._index.get(artifact_id)
            if meta is None:
                raise ArtifactNotFoundError(
                    f"no artifact with id {artifact_id!r}"
                )
            return meta["summary"]

    def get_report(self, artifact_id: str) -> object:
        """Return the full report body (the expensive tier)."""
        with self._lock:
            if artifact_id not in self._index:
                raise ArtifactNotFoundError(
                    f"no artifact with id {artifact_id!r}"
                )
            return self._read_report(artifact_id)

    def exists(self, artifact_id: str) -> bool:
        """True when an artifact with *artifact_id* is stored."""
        with self._lock:
            return artifact_id in self._index

    def list_ids(self) -> list[str]:
        """Return all stored artifact ids (stable order)."""
        with self._lock:
            return sorted(self._index)

    def count(self) -> int:
        """Return the number of stored artifacts."""
        with self._lock:
            return len(self._index)

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def _load_index(self) -> None:
        if not self._index_path.exists():
            return
        try:
            data = json.loads(self._index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"artifact index {self._index_path} is corrupt: {exc}"
            ) from exc
        if not isinstance(data, dict):
            raise ValueError(
                f"artifact index {self._index_path} must be a JSON object"
            )
        for aid, meta in data.items():
            if not isinstance(meta, dict) or not isinstance(
                meta.get("headline"), str
            ) or not isinstance(meta.get("summary"), str):
                raise ValueError(
                    f"artifact index entry {aid!r} is malformed"
                )
        self._index = data

    def _save_index(self) -> None:
        # Atomic-ish: write temp then rename so a crash cannot leave a
        # half-written index.
        tmp = self._index_path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._index, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self._index_path)

    def _report_path(self, artifact_id: str) -> Path:
        return self._artifacts_dir / f"{artifact_id}.json"

    def _write_report(self, artifact_id: str, report: object) -> None:
        path = self._report_path(artifact_id)
        if path.exists():
            # Same content address => same body; nothing to do.
            return
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)

    def _read_report(self, artifact_id: str) -> object:
        path = self._report_path(artifact_id)
        if not path.exists():
            raise ArtifactNotFoundError(
                f"artifact {artifact_id!r} is indexed but its report body "
                f"is missing at {path}"
            )
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ValueError(
                f"artifact report {path} is corrupt: {exc}"
            ) from exc


class BoundaryEventLog:
    """Append-only JSON-lines log of boundary events (INFO-049).

    Five event kinds: ``spawned``, ``settled``, ``cancelled``, ``published``,
    ``messaged``. Each line is one JSON object::

        {"kind": "spawned", "causal_id": null, "agent_id": "...",
         "payload": {...}, "ts": "2026-10-06T23:03:25+00:00"}

    ``payload`` carries by-reference ids only (artifact ids, child ids) —
    never full bodies. ``causal_id`` links an event to the event that caused
    it (e.g. a ``settled`` event references the ``spawned`` event's id).
    """

    def __init__(self, artifact_root: Path) -> None:
        self._path = Path(artifact_root) / _BOUNDARY_LOG_NAME
        self._lock = threading.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        """The log file path."""
        return self._path

    def append(
        self,
        kind: str,
        agent_id: str,
        causal_id: Optional[str] = None,
        payload: Optional[dict[str, Any]] = None,
    ) -> dict:
        """Append one boundary event and return the recorded line as a dict.

        Raises :class:`ValueError` for an unknown *kind*.
        """
        if kind not in BOUNDARY_EVENT_KINDS:
            raise ValueError(
                f"unknown boundary event kind {kind!r}; expected one of "
                f"{sorted(BOUNDARY_EVENT_KINDS)}"
            )
        event = {
            "kind": kind,
            "causal_id": causal_id,
            "agent_id": agent_id,
            "payload": payload if payload is not None else {},
            "ts": _iso(_utcnow()),
        }
        line = json.dumps(event, ensure_ascii=False, sort_keys=True)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
                fh.flush()
        return event

    def read(
        self,
        agent_id: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> list[dict]:
        """Return all events, optionally filtered by *agent_id* and/or *kind*.

        Events are returned in append order (oldest first).
        """
        if kind is not None and kind not in BOUNDARY_EVENT_KINDS:
            raise ValueError(
                f"unknown boundary event kind {kind!r}; expected one of "
                f"{sorted(BOUNDARY_EVENT_KINDS)}"
            )
        events: list[dict] = []
        if not self._path.exists():
            return events
        with self._lock:
            with self._path.open("r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except ValueError as exc:
                        raise ValueError(
                            f"corrupt boundary event line in {self._path}: {exc}"
                        ) from exc
                    if agent_id is not None and event.get("agent_id") != agent_id:
                        continue
                    if kind is not None and event.get("kind") != kind:
                        continue
                    events.append(event)
        return events
