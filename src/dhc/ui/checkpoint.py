"""Per-agent checkpoint persistence (peripheral wrapper).

Decision 0016 home: the operator's side (``dhc.ui``) — the operator's
resumability mechanism, next to the operator's review files
(:mod:`dhc.ui.state`).

Mirrors the reference project's ``core/checkpoint.py`` pattern: an
``AgentCheckpoint`` pydantic model persisted as
``<checkpoint_root>/<agent_id>.json`` via ``model_dump_json(indent=2)``.

This module is a *peripheral wrapper*: it does not import or modify the core
(``runtime.py`` / ``event_stream.py``). ``CheckpointDriver`` wraps a driver
callable (``driver(agent) -> str | None``) and persists state before and after
each turn, best-effort — a store failure is logged and never breaks the driver
loop.

**Operator-only (decision 0012, H-06).** This on-disk store is the
*operator's* resumability mechanism, surfaced via the terminal's ``/resume``.
It is deliberately separate from the *agent's* own workspace checkpoints
(``state["checkpoints"]`` in the fabrication kit, ``dhc.tooling.fabrication``),
which live in the agent's context as ordinary data. The split is intended:
the agent owns its context, the operator owns the runtime's durable state.
The store is not instantiated in production wiring (``build_runtime``), so it
is dormant until an operator attaches it.
"""

from __future__ import annotations

import logging
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentCheckpoint(BaseModel):
    """Structured, on-disk snapshot of an agent's running state.

    Captured automatically before and after each driver turn so an aborted or
    failed run can be resumed from a fresh process.
    """

    agent_id: str
    requirement: str = ""
    acceptance: list[str] = Field(default_factory=list)
    status: str | None = None
    turn_counter: int = 0
    checkpoint_notes: list[str] = Field(default_factory=list)
    updated_at: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


def checkpoint_from_agent(
    agent: Any,
    turn_counter: int,
    notes: Optional[list[str]] = None,
    extra: Optional[dict[str, Any]] = None,
) -> AgentCheckpoint:
    """Build an ``AgentCheckpoint`` from a dhc Agent (duck-typed)."""
    status = getattr(agent, "_status", None)
    if status is None:
        status = getattr(agent, "status", None)
    if callable(status):
        status = None
    if hasattr(status, "value"):
        status = status.value
    acceptance = getattr(agent, "acceptance", ()) or ()
    if not isinstance(acceptance, (list, tuple)):
        acceptance = (acceptance,)
    return AgentCheckpoint(
        agent_id=str(getattr(agent, "id", "")),
        requirement=str(getattr(agent, "requirement", "") or ""),
        acceptance=[str(a) for a in acceptance],
        status=str(status) if status is not None else None,
        turn_counter=int(turn_counter),
        checkpoint_notes=list(notes or []),
        updated_at=_utcnow_iso(),
        extra=dict(extra or {}),
    )


class CheckpointStore:
    """Persists and reloads ``AgentCheckpoint`` records keyed by agent id.

    Writes are atomic (tmp file + ``os.replace``) and best-effort: a failure
    (e.g. a read-only root) is logged and never raised to the caller.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("CheckpointStore: cannot create root %s", self.root)

    def _path(self, agent_id: str) -> Path:
        return self.root / f"{agent_id}.json"

    def save(self, checkpoint: AgentCheckpoint) -> Path:
        """Write *checkpoint* to ``<root>/<agent_id>.json`` (atomic, best-effort).

        Returns the target path whether or not the write succeeded; failures
        are logged, never raised.
        """
        target = self._path(checkpoint.agent_id)
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            payload = checkpoint.model_dump_json(indent=2)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self.root), prefix=f".{checkpoint.agent_id}.", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(payload)
                os.replace(tmp_name, target)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except Exception as exc:  # noqa: BLE001 - best-effort by design
            logger.warning(
                "CheckpointStore: failed to save checkpoint for %s: %s",
                checkpoint.agent_id,
                exc,
            )
        return target

    def load(self, agent_id: str) -> Optional[AgentCheckpoint]:
        p = self._path(agent_id)
        try:
            if not p.exists():
                return None
            return AgentCheckpoint.model_validate_json(p.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - a corrupt file is not fatal
            logger.warning("CheckpointStore: failed to load %s: %s", agent_id, exc)
            return None

    def list_ids(self) -> list[str]:
        ids: list[str] = []
        for p in sorted(self.root.glob("*.json")):
            cp = self.load(p.stem)
            if cp is not None:
                ids.append(cp.agent_id)
        return ids


class CheckpointDriver:
    """Driver wrapper that persists a checkpoint before and after each turn.

    Wraps a driver callable ``driver(agent) -> str | None``. Before delegating
    to the wrapped driver a checkpoint is saved with ``turn_counter``
    incremented; after the wrapped driver returns, the checkpoint is saved
    again — mirroring the reference's "after every committed turn and before
    each LLM call". Persistence is best-effort: a store failure never breaks
    the driver loop.

    ``interval`` throttles the *before* save (every ``interval`` turns); the
    *after* save always runs. With the default ``interval=1`` both saves run
    on every call.
    """

    def __init__(
        self,
        driver: Callable[[Any], Optional[str]],
        store: CheckpointStore,
        interval: int = 1,
    ) -> None:
        self.driver = driver
        self.store = store
        self.interval = max(1, int(interval))
        self._counters: dict[str, int] = {}
        self._notes: dict[str, list[str]] = {}

    def _state(self, agent_id: str) -> tuple[int, list[str]]:
        if agent_id not in self._counters:
            cp = self.store.load(agent_id)
            self._counters[agent_id] = cp.turn_counter if cp is not None else 0
            self._notes[agent_id] = list(cp.checkpoint_notes) if cp is not None else []
        return self._counters[agent_id], self._notes[agent_id]

    def _save(self, agent: Any, turn_counter: int, note: str) -> None:
        try:
            agent_id = str(getattr(agent, "id", ""))
            _, notes = self._state(agent_id)
            notes.append(note)
            cp = checkpoint_from_agent(
                agent,
                turn_counter,
                notes=list(notes),
                extra={"driver": type(self.driver).__name__},
            )
            self.store.save(cp)
        except Exception as exc:  # noqa: BLE001 - best-effort by design
            logger.warning("CheckpointDriver: checkpoint save failed: %s", exc)

    def __call__(self, agent: Any) -> Optional[str]:
        agent_id = str(getattr(agent, "id", ""))
        counter, _ = self._state(agent_id)
        counter += 1
        self._counters[agent_id] = counter
        if counter == 1 or counter % self.interval == 0:
            self._save(agent, counter, f"before turn {counter}")
        try:
            result = self.driver(agent)
        except BaseException:
            # Persist the failure state, then re-raise so the runtime's usual
            # containment handles the driver failure.
            self._save(agent, counter, f"after turn {counter} (driver raised)")
            raise
        self._save(agent, counter, f"after turn {counter}")
        return result