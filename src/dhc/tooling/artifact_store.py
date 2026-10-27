"""Immutable, content-addressed artifact store and boundary event log.

Operator tooling (decision 0014): the framework core (``dhc.framework``) knows
artifacts only as opaque ids and the ``artifact_published`` event kind —
everything that *persists* them lives here.

Artifacts (INFO-006) are the durable medium of the runtime: every finding,
result, and action's code persists as an immutable, content-addressed
artifact. Consumers pull progressive-disclosure tiers on demand —
``headline`` -> ``summary`` -> ``report`` — and handoffs between siblings are
addressed by content hash so they are safe to repeat and verify.

Storage layout under ``settings.artifact_root``::

    artifact_root/
        index.json                 # headline + summary per artifact id
        artifacts/<id>.json        # full report body per artifact
        boundary-events.jsonl      # append-only boundary event log (INFO-049)
        metadata-conflicts.jsonl   # set-once metadata violations (INFO-006)
        .artifact-store.lock       # advisory cross-process lock file

Durability and concurrency
--------------------------
Every body and index write is atomic: the payload is written to a temporary
file in the *same* directory, ``flush`` + ``os.fsync`` discard the kernel
buffers, and ``os.replace`` publishes it. A crash mid-write therefore leaves
either the previous file or the complete new file — never a torn body.

``put`` also holds an exclusive advisory file lock (``fcntl.flock`` on
``.artifact-store.lock``) across the whole create-and-index-update critical
section, so concurrent writers in *different processes* are serialised rather
than racing. Because the artifact id is the sha256 content address, racing
writers of the same id necessarily carry the same body: the loser observes
the winner's file, verifies it against its own body, and returns the existing
id without rewriting anything. (On platforms without ``fcntl`` the lock
degrades to the in-process :class:`threading.Lock` only.)

Immutable metadata (set-once rule)
----------------------------------
Artifact bodies are immutable by construction, and so is the index metadata
that describes them. ``headline`` and ``summary`` are written exactly once,
by the first ``put`` that creates the id. A later ``put`` of the same id may
only *match* those values; a differing value is ignored — the stored metadata
wins and the attempt is appended to ``metadata-conflicts.jsonl`` with
``reason: "immutable_metadata"``, the differing fields, and both values.
Silent overwrites are forbidden: the audit trail must never change
retroactively. Readers see the first writer's tiers forever.

The store is thread-safe (a single :class:`threading.Lock` guards all
mutations and the in-memory index) and survives reopen: the JSON index is
reloaded on construction and refreshed whenever the on-disk index changes
(so a second process's publications become visible). Stored artifacts are
never mutated.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

try:  # POSIX advisory locking; absent on Windows.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platform guard
    fcntl = None  # type: ignore[assignment]

from ..errors import ArtifactNotFoundError
from ..data.models import Artifact

#: The five boundary event kinds (INFO-049).
BOUNDARY_EVENT_KINDS: frozenset[str] = frozenset(
    {"spawned", "settled", "cancelled", "published", "messaged"}
)

_INDEX_NAME = "index.json"
_ARTIFACTS_DIR = "artifacts"
_BOUNDARY_LOG_NAME = "boundary-events.jsonl"
_METADATA_CONFLICTS_NAME = "metadata-conflicts.jsonl"
_LOCK_NAME = ".artifact-store.lock"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(ts: datetime) -> str:
    """Serialize a datetime to a stable, sortable ISO-8601 string."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).isoformat()


def _canonical(value: object) -> str:
    """Canonical JSON text used as the stored body representation."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _fsync_dir(path: Path) -> None:
    """Best-effort fsync of a directory so a rename survives a power loss."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:  # pragma: no cover - directory vanished
        return
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover - e.g. unusual filesystem
        pass
    finally:
        os.close(fd)


def _atomic_write_text(path: Path, text: str) -> None:
    """Write *text* to *path* atomically and durably.

    Temp file in the same directory -> flush -> ``os.fsync`` -> ``os.replace``
    -> fsync the directory. Any failure removes the temp file and leaves the
    previous contents of *path* untouched.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:  # pragma: no cover - already gone
            pass
        raise
    _fsync_dir(path.parent)


@contextmanager
def _advisory_lock(lock_path: Path) -> Iterator[None]:
    """Exclusive cross-process advisory lock around a critical section.

    No-op where ``fcntl`` is unavailable (non-POSIX); the in-process
    :class:`threading.Lock` still guards concurrent threads there.
    """
    if fcntl is None:  # pragma: no cover - non-POSIX platform guard
        yield
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


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
        self._lock_path = self._root / _LOCK_NAME
        self._conflicts_path = self._root / _METADATA_CONFLICTS_NAME
        self._lock = threading.Lock()
        #: id -> {"headline": str, "summary": str}
        self._index: dict[str, dict[str, str]] = {}
        #: (st_mtime_ns, st_size) of the index file when it was last loaded.
        self._index_stamp: Optional[tuple[int, int]] = None
        self._load_index()

    @property
    def root(self) -> Path:
        """The store's root directory."""
        return self._root

    @property
    def metadata_conflicts_path(self) -> Path:
        """Append-only log of rejected (set-once) metadata writes."""
        return self._conflicts_path

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def put(self, artifact: Artifact) -> str:
        """Store *artifact* and return its content address (id).

        Idempotent for identical content: putting the same body twice returns
        the same id and does not duplicate storage. Raises
        :class:`ValueError` if the artifact's id maps to different content
        (defensive; :class:`~dhc.models.Artifact` already validates this), or
        if the body already on disk does not match the incoming one.

        The create-and-index-update step runs under an exclusive cross-process
        advisory lock, so concurrent publishers of the same id converge on a
        single body; the loser verifies the winner's body and returns its id.
        ``headline``/``summary`` are set once — a differing re-publish is
        ignored and logged (see the module docstring).
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
            with _advisory_lock(self._lock_path):
                # Another process may have published this id since our last
                # load; re-read before deciding who creates the body.
                self._refresh_index_locked()
                existing = self._index.get(aid)
                if existing is not None:
                    self._verify_existing_locked(aid, artifact)
                    self._note_metadata_locked(aid, existing, artifact)
                    return aid
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
            meta = self._meta(artifact_id)
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
            return self._meta(artifact_id)["headline"]

    def get_summary(self, artifact_id: str) -> str:
        """Return the middle progressive-disclosure tier."""
        with self._lock:
            return self._meta(artifact_id)["summary"]

    def get_report(self, artifact_id: str) -> object:
        """Return the full report body (the expensive tier)."""
        with self._lock:
            self._meta(artifact_id)
            return self._read_report(artifact_id)

    def exists(self, artifact_id: str) -> bool:
        """True when an artifact with *artifact_id* is stored."""
        with self._lock:
            return self._meta(artifact_id, required=False) is not None

    def list_ids(self) -> list[str]:
        """Return all stored artifact ids (stable order)."""
        with self._lock:
            self._refresh_index_locked()
            return sorted(self._index)

    def count(self) -> int:
        """Return the number of stored artifacts."""
        with self._lock:
            self._refresh_index_locked()
            return len(self._index)

    # ------------------------------------------------------------------ #
    # Lookup helpers
    # ------------------------------------------------------------------ #

    def _meta(
        self, artifact_id: str, required: bool = True
    ) -> Optional[dict[str, str]]:
        """Return the index entry for *artifact_id* (refreshing from disk).

        Raises :class:`ArtifactNotFoundError` when *required* and absent.
        """
        self._refresh_index_locked()
        meta = self._index.get(artifact_id)
        if meta is None and required:
            raise ArtifactNotFoundError(
                f"no artifact with id {artifact_id!r}"
            )
        return meta

    def _verify_existing_locked(
        self, artifact_id: str, artifact: Artifact
    ) -> None:
        """Confirm the stored body equals *artifact*'s body, repairing a gap."""
        path = self._report_path(artifact_id)
        if not path.exists():
            # Index entry without a body (e.g. manually deleted): heal it from
            # the incoming artifact, which is the same content by definition.
            self._write_report(artifact_id, artifact.report)
            return
        stored = _canonical(self._read_report(artifact_id))
        incoming = _canonical(artifact.report)
        if stored != incoming:
            raise ValueError(
                f"artifact {artifact_id!r} is already stored with a different "
                f"body; refusing to overwrite an immutable artifact"
            )

    def _note_metadata_locked(
        self,
        artifact_id: str,
        existing: dict[str, str],
        artifact: Artifact,
    ) -> None:
        """Apply the set-once rule for headline/summary (log-only on conflict)."""
        incoming = {"headline": artifact.headline, "summary": artifact.summary}
        differing = sorted(
            field for field, value in incoming.items()
            if existing.get(field) != value
        )
        if not differing:
            return
        record = {
            "id": artifact_id,
            "reason": "immutable_metadata",
            "fields": differing,
            "stored": {f: existing.get(f) for f in differing},
            "incoming": {f: incoming[f] for f in differing},
            "ts": _iso(_utcnow()),
        }
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with self._conflicts_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #

    def _load_index(self) -> None:
        try:
            st = self._index_path.stat()
        except OSError:
            self._index_stamp = None
            return
        self._index_stamp = (st.st_mtime_ns, st.st_size)
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

    def _refresh_index_locked(self) -> None:
        """Reload the index when another process has replaced it on disk."""
        try:
            st = self._index_path.stat()
        except OSError:
            return
        if (st.st_mtime_ns, st.st_size) == self._index_stamp:
            return
        self._load_index()

    def _save_index(self) -> None:
        # Atomic and durable: temp -> fsync -> rename, so a crash cannot leave
        # a half-written index.
        _atomic_write_text(
            self._index_path,
            json.dumps(self._index, ensure_ascii=False, sort_keys=True),
        )
        st = self._index_path.stat()
        self._index_stamp = (st.st_mtime_ns, st.st_size)

    def _report_path(self, artifact_id: str) -> Path:
        return self._artifacts_dir / f"{artifact_id}.json"

    def _write_report(self, artifact_id: str, report: object) -> None:
        path = self._report_path(artifact_id)
        if path.exists():
            # Same content address => same body; nothing to do.
            return
        _atomic_write_text(path, _canonical(report))

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
