"""Per-agent trace persistence (peripheral wrapper).

Mirrors the reference project's ``core/trace.py`` pattern: an append-only
``trace.jsonl`` per agent under ``<trace_root>/<agent_id>/trace.jsonl`` with
entry types ``llm_request`` / ``llm_response`` / ``tool_call`` /
``tool_result`` / ``event``.

This module is a *peripheral wrapper*: it does not import or modify the core
(``runtime.py`` / ``event_stream.py``). ``TracingEngine`` wraps an engine
(duck-typed to ``engine.execute(agent_id, code, namespace, timeout) -> Result``)
and records a ``tool_call`` entry before delegating and a ``tool_result`` entry
after, returning the wrapped result unchanged. All writes are best-effort: a
trace failure is logged and never breaks the engine loop.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Valid trace entry types (mirror the reference).
ENTRY_TYPES = frozenset(
    {"llm_request", "llm_response", "tool_call", "tool_result", "event"}
)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TraceStore:
    """Append-only per-agent ``trace.jsonl`` store.

    Each entry is one JSON line: ``{"ts": <ms>, "timestamp": <iso>, "type":
    <entry_type>, **data}``. Writes are best-effort: a failure (e.g. a
    read-only root) is logged and never raised to the caller.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("TraceStore: cannot create root %s", self.root)

    def _agent_dir(self, agent_id: str) -> Path:
        d = self.root / agent_id
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError:
            logger.warning("TraceStore: cannot create agent dir %s", d)
        return d

    def path_for(self, agent_id: str) -> Path:
        """Return the trace file path for *agent_id* (dirs created)."""
        return self._agent_dir(agent_id) / "trace.jsonl"

    def append(self, agent_id: str, entry_type: str, data: dict[str, Any]) -> None:
        """Append one JSON line to ``<root>/<agent_id>/trace.jsonl``.

        Best-effort: failures are logged, never raised.
        """
        if entry_type not in ENTRY_TYPES:
            logger.warning("TraceStore: unknown entry type %r", entry_type)
        entry = {
            "ts": _now_ms(),
            "timestamp": _utcnow_iso(),
            "type": entry_type,
            **dict(data or {}),
        }
        try:
            path = self.path_for(agent_id)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")
        except Exception as exc:  # noqa: BLE001 - best-effort by design
            logger.warning(
                "TraceStore: failed to append %s for %s: %s",
                entry_type,
                agent_id,
                exc,
            )

    def read(self, agent_id: str) -> list[dict[str, Any]]:
        """Read all entries for *agent_id* as a list of dicts."""
        path = self.path_for(agent_id)
        entries: list[dict[str, Any]] = []
        try:
            if not path.exists():
                return entries
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        except Exception as exc:  # noqa: BLE001 - a corrupt trace is not fatal
            logger.warning("TraceStore: failed to read %s: %s", agent_id, exc)
        return entries


class TracingEngine:
    """Engine wrapper that records tool_call / tool_result trace entries.

    Duck-typed to the runtime's engine contract:
    ``execute(agent_id, code, namespace=None, timeout=None) -> Result``.
    Records a ``tool_call`` entry (code, agent_id) before delegating to the
    wrapped engine and a ``tool_result`` entry (result summary) after, then
    returns the wrapped result unchanged. Tracing is best-effort: a trace
    failure never breaks the engine loop.
    """

    def __init__(self, engine: Any, trace_store: TraceStore) -> None:
        self.engine = engine
        self.trace_store = trace_store

    def execute(
        self,
        agent_id: str,
        code: str,
        namespace: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        started = _now_ms()
        self.trace_store.append(
            agent_id,
            "tool_call",
            {
                "agent_id": agent_id,
                "code": code,
                "namespace_keys": sorted(namespace.keys()) if namespace else [],
                "timeout": timeout,
            },
        )
        try:
            result = self.engine.execute(
                agent_id, code, namespace=namespace, timeout=timeout
            )
        except BaseException as exc:
            self.trace_store.append(
                agent_id,
                "tool_result",
                {
                    "agent_id": agent_id,
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "duration_ms": _now_ms() - started,
                },
            )
            raise
        self.trace_store.append(
            agent_id,
            "tool_result",
            {
                "agent_id": agent_id,
                "ok": bool(getattr(result, "ok", None)),
                "done": bool(getattr(result, "done", None)),
                "reason": str(getattr(result, "reason", "") or ""),
                "artifacts": list(getattr(result, "artifacts", []) or []),
                "duration_ms": _now_ms() - started,
            },
        )
        return result