"""Persist run overview + event stream to files for manual review.

Adopts the reference project's ``cli/state.py`` + ``cli/present.py`` pattern:
the terminal keeps prompts and a final outcome line; everything else that was
previously rendered live (agent tree, status, events) is written as files
under the run root for traceability and post-hoc / automated inspection.

The four run-overview files:

- ``agent_tree.json`` — JSON array of root nodes, recursive ``children``.
- ``stats.json`` — aggregate counters over the whole tree.
- ``agents.txt`` — plain-text box-drawn tree (``└/├/│`` branches).
- ``events.jsonl`` — append-only, one JSON line per event.

This module is peripheral (not core): it reads the runtime's public API only
(``get``/``children_of``/``status``/``result``/``is_settled`` and the
``_agents`` registry) and never imports or modifies ``runtime.py`` /
``event_stream.py``.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..data.models import AgentStatus, Result

ID_CHARS = 8
TREE_DESC_CHARS = 40


def _clip(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[:n]


def _clip_description(text: str, n: int) -> str:
    """Clip a description to at most ``n`` chars, cutting at a word boundary
    and appending ``…`` when truncated so it never ends midline."""
    if len(text) <= n:
        return text
    cut = text[: n - 1].rstrip()
    cut = cut.rsplit(" ", 1)[0]
    return cut + "…"


def cache_hit_rate(prompt_tokens: int, cached_tokens: int) -> float:
    """Fraction of billed prompt tokens that the provider cache covered.

    ``cached_tokens`` counts tokens read from the cache within the billed
    prompt (``prompt_tokens``), so the ratio is ``cached / prompt``. A
    zero-denominator (no prompt tokens reported) yields ``0.0``.
    """
    if prompt_tokens <= 0:
        return 0.0
    return min(1.0, cached_tokens / prompt_tokens)


def fmt_usd(cost: float) -> str:
    """Compact USD formatting: whole dollars → 2dp, cents → 4dp, else 6dp."""
    if cost >= 1:
        return f"{cost:.2f}"
    if cost >= 0.01:
        return f"{cost:.4f}"
    return f"{cost:.6f}"


def fmt_int(n: int) -> str:
    """Thousands-separated with apostrophes: 1000000 → ``1'000'000``."""
    return f"{n:,}".replace(",", "'")


@dataclass
class AgentNode:
    """Tree node view-model: engine-agnostic representation of one agent."""

    agent_id: str
    description: str
    status: str
    tokens: int = 0
    messages: int = 0
    context_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0
    cum_cost_usd: float = 0.0
    artifact_ids: list[str] = field(default_factory=list)
    trace_path: Optional[str] = None
    children: list["AgentNode"] = field(default_factory=list)

    @property
    def short_id(self) -> str:
        return _clip(self.agent_id, ID_CHARS)

    @property
    def short_description(self) -> str:
        return _clip_description(self.description, TREE_DESC_CHARS)

    @property
    def cache_hit_rate(self) -> float:
        return cache_hit_rate(self.prompt_tokens, self.cached_tokens)

    @property
    def usage(self) -> str:
        if not (self.tokens or self.messages or self.prompt_tokens
                or self.completion_tokens or self.cost_usd or self.cum_cost_usd):
            return ""
        parts = []
        if self.context_tokens:
            parts.append(f"ctx {fmt_int(self.context_tokens)}")
        if self.messages:
            parts.append(f"{fmt_int(self.messages)}msgs")
        if self.prompt_tokens or self.completion_tokens:
            parts.append(f"in {fmt_int(self.prompt_tokens)}")
            parts.append(f"out {fmt_int(self.completion_tokens)}")
            pct = round(self.cache_hit_rate * 100)
            parts.append(f"cache {pct}%")
        elif self.tokens:
            parts.append(f"{fmt_int(self.tokens)}t")
        if self.cost_usd:
            parts.append(f"${fmt_usd(self.cost_usd)}")
        if self.cum_cost_usd and self.cum_cost_usd != self.cost_usd:
            parts.append(f"Σ${fmt_usd(self.cum_cost_usd)}")
        return f" ({', '.join(parts)})"


@dataclass
class Stats:
    agents: int = 0
    commits: int = 0
    tokens: int = 0
    prompt_tokens: int = 0
    cached_tokens: int = 0
    cache_hit_rate: float = 0.0
    cost_usd: float = 0.0


def _agent_status(runtime: Any, agent_id: str) -> str:
    """Return the agent's status as a string, tolerating unsettled agents."""
    try:
        status = runtime.status(agent_id)
    except Exception:  # noqa: BLE001 - view-model must never crash a snapshot
        return AgentStatus.pending.value
    if isinstance(status, AgentStatus):
        return status.value
    return str(status)


def _agent_result_artifacts(runtime: Any, agent_id: str) -> list[str]:
    """Return the settled result's artifact ids, or [] when unavailable.

    dhc's ``Agent._result`` (returned by ``runtime.result``) does not carry
    artifacts — they live on ``Agent._last_result`` (the Result produced by
    ``complete(..., artifacts=...)``) and on the settled Completion. Read
    ``_last_result`` first, then fall back to ``runtime.result``.
    """
    agents = getattr(runtime, "_agents", None)
    if agents is not None and agent_id in agents:
        last = getattr(agents[agent_id], "_last_result", None)
        if last is not None:
            artifacts = getattr(last, "artifacts", None)
            if artifacts:
                return list(artifacts)
    try:
        result = runtime.result(agent_id)
    except Exception:  # noqa: BLE001 - view-model must never crash a snapshot
        return []
    if isinstance(result, Result):
        return list(result.artifacts)
    artifacts = getattr(result, "artifacts", None)
    if artifacts is None:
        return []
    return list(artifacts)


def build_agent_tree(runtime: Any) -> list[AgentNode]:
    """Walk the runtime's agent registry into nested AgentNode view-models.

    Roots are agents whose ``parent_id`` is None (or whose parent is not
    registered). Children are resolved via ``runtime.children_of``; the
    registry is read through ``runtime._agents`` (the runtime's public
    ``get``/``children_of``/``status``/``result``/``is_settled`` API plus the
    documented ``_agents`` registry). Token/cost fields are copied from the
    agent's accumulators (the driver seam's ``record_usage``, IMP-004);
    agents without usage (mock path) keep the zero defaults.
    """
    agents = getattr(runtime, "_agents", None)
    if agents is None:
        return []
    agent_ids = list(agents.keys())

    def build(aid: str) -> AgentNode:
        agent = agents[aid]
        description = getattr(agent, "requirement", "") or ""
        children = [
            build(cid)
            for cid in runtime.children_of(aid)
            if cid in agents
        ]
        # The ONE read seam (IMP-004): copy the agent's accumulated usage
        # (written only by the driver seam via ``record_usage``) into the
        # view-model. Agents without accumulators (mock path, foreign
        # objects) keep the zero defaults.
        prompt_tokens = int(getattr(agent, "prompt_tokens", 0) or 0)
        completion_tokens = int(getattr(agent, "completion_tokens", 0) or 0)
        cached_tokens = int(getattr(agent, "cached_tokens", 0) or 0)
        cost_usd = float(getattr(agent, "cost_usd", 0.0) or 0.0)
        return AgentNode(
            agent_id=aid,
            description=description,
            status=_agent_status(runtime, aid),
            tokens=prompt_tokens + completion_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cached_tokens=cached_tokens,
            cost_usd=cost_usd,
            cum_cost_usd=cost_usd,
            artifact_ids=_agent_result_artifacts(runtime, aid),
            children=children,
        )

    roots = [
        aid
        for aid in agent_ids
        if getattr(agents[aid], "parent_id", None) is None
        or agents[aid].parent_id not in agents
    ]
    return [build(aid) for aid in roots]


def build_stats(runtime: Any) -> Stats:
    """Aggregate counters over the whole agent tree.

    Token/cost counters sum the node values (which the driver seam's
    ``record_usage`` populates, IMP-004); the cache hit rate is the
    aggregate ``cached / prompt`` over the whole tree.
    """
    nodes = build_agent_tree(runtime)

    def walk(nodes: list[AgentNode]) -> int:
        return sum(1 + walk(node.children) for node in nodes)

    def sum_field(nodes: list[AgentNode], field: str) -> float:
        return sum(
            getattr(node, field) + sum_field(node.children, field)
            for node in nodes
        )

    prompt_tokens = int(sum_field(nodes, "prompt_tokens"))
    cached_tokens = int(sum_field(nodes, "cached_tokens"))
    return Stats(
        agents=walk(nodes),
        tokens=int(sum_field(nodes, "tokens")),
        prompt_tokens=prompt_tokens,
        cached_tokens=cached_tokens,
        cache_hit_rate=cache_hit_rate(prompt_tokens, cached_tokens),
        cost_usd=float(sum_field(nodes, "cost_usd")),
    )


def render_text_tree(nodes: list[AgentNode]) -> str:
    """Plain-text agent tree for quick operator evaluation.

    One line per agent: ``{branch} {short_id} [{status}] {short_description}``
    with ``└/├/│`` branches. Engine-agnostic (no terminal-library markup) so
    it can be persisted to disk.
    """
    if not nodes:
        return "(no agents)\n"

    lines: list[str] = []

    def walk(nodes: list[AgentNode], prefix: str) -> None:
        for i, node in enumerate(nodes):
            is_last = i == len(nodes) - 1
            branch = "└" if is_last else "├"
            lines.append(
                f"{prefix}{branch} {node.short_id} [{node.status}] "
                f"{node.short_description}{node.usage}"
            )
            child_prefix = prefix + ("  " if is_last else "│ ")
            walk(node.children, child_prefix)

    walk(nodes, "")
    return "\n".join(lines) + "\n"


def _node_dict(node: AgentNode) -> dict[str, Any]:
    return {
        "agent_id": node.agent_id,
        "description": node.description,
        "status": node.status,
        "tokens": node.tokens,
        "messages": node.messages,
        "context_tokens": node.context_tokens,
        "prompt_tokens": node.prompt_tokens,
        "completion_tokens": node.completion_tokens,
        "cached_tokens": node.cached_tokens,
        "cache_hit_rate": node.cache_hit_rate,
        "cost_usd": node.cost_usd,
        "cum_cost_usd": node.cum_cost_usd,
        "artifact_ids": node.artifact_ids,
        "trace_path": node.trace_path,
        "children": [_node_dict(c) for c in node.children],
    }


def _default_root(runtime: Any) -> Path:
    """Run root = artifact root's parent, else workspace_root/.dynamic-harness."""
    settings = getattr(runtime, "settings", None)
    artifact_root = getattr(settings, "artifact_root", None) if settings is not None else None
    if artifact_root is not None:
        return Path(artifact_root).parent
    workspace_root = getattr(settings, "workspace_root", None) if settings is not None else None
    if workspace_root is not None:
        return Path(workspace_root) / ".dynamic-harness"
    return Path.cwd() / ".dynamic-harness"


class StateWriter:
    """Append-only ``events.jsonl`` plus latest ``agent_tree.json``/``stats.json``.

    All four sit in the run root (parent of the artifact root), next to
    ``artifacts/``, ``repo/``, and ``traces/`` for one-run overviews.
    """

    def __init__(
        self,
        runtime: Any,
        root: Optional[Path] = None,
        snapshot_interval: float = 5.0,
    ) -> None:
        self.runtime = runtime
        self.root = Path(root) if root is not None else _default_root(runtime)
        self.root.mkdir(parents=True, exist_ok=True)
        self.tree_path = self.root / "agent_tree.json"
        self.stats_path = self.root / "stats.json"
        self.events_path = self.root / "events.jsonl"
        self.agents_txt_path = self.root / "agents.txt"
        # Throttle for activity-driven snapshots: don't rewrite the tree on
        # every LLM/tool event (build_agent_tree has a cost per call), only at
        # most once per interval. Terminal events always force a flush.
        self.snapshot_interval = snapshot_interval
        self._last_snapshot = 0.0

    def snapshot(self, force: bool = False) -> None:
        """Rewrite agent_tree.json + stats.json + agents.txt (text overview).

        Callers that fire frequently (activity events) omit ``force`` so the
        write is throttled to at most once per ``snapshot_interval``; terminal
        events (report / failure / escalation) pass ``force=True`` to guarantee
        the tree reflects the final state immediately.
        """
        now = time.monotonic()
        if not force and now - self._last_snapshot < self.snapshot_interval:
            return
        self._last_snapshot = now
        # Build the tree once and reuse for both JSON and text output (building
        # it twice doubles the registry scan on every terminal event).
        nodes = build_agent_tree(self.runtime)
        self.tree_path.write_text(
            json.dumps([_node_dict(n) for n in nodes], indent=2)
        )
        self.stats_path.write_text(
            json.dumps(asdict(build_stats(self.runtime)), indent=2)
        )
        self.agents_txt_path.write_text(render_text_tree(nodes))

    def append_event(
        self, event: dict[str, Any], ts: Optional[datetime] = None
    ) -> None:
        """Append one structured event to events.jsonl (never truncated)."""
        line = {"ts": (ts or datetime.now(timezone.utc)).isoformat(), **event}
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")

    def attach(self, runtime: Any = None) -> None:
        """Subscribe to the runtime's event bus (if it has one).

        Terminal events (report / failure / escalation) trigger force
        snapshots + events.jsonl appends; activity events trigger throttled
        snapshots. Also writes one snapshot at attach.
        """
        runtime = runtime if runtime is not None else self.runtime
        bus = getattr(runtime, "event_bus", None)
        if bus is None:
            # No bus: still write the initial snapshot so the overview files
            # exist for manual review.
            self.snapshot(force=True)
            return

        def on_event(event: Any) -> None:
            kind = getattr(event, "kind", None)
            kind_value = kind.value if hasattr(kind, "value") else str(kind)
            agent_id = getattr(event, "agent_id", "")
            payload = getattr(event, "payload", None) or {}
            ts = getattr(event, "ts", None)
            if kind_value == "report":
                self.append_event({
                    "event": "report",
                    "agent_id": agent_id,
                    "summary": payload.get("summary", ""),
                    "confidence": payload.get("confidence"),
                    "artifact_ids": payload.get("artifact_ids", []),
                    "files_written": payload.get("files_written", []),
                }, ts=ts)
                self.snapshot(force=True)
            elif kind_value == "failure":
                self.append_event({
                    "event": "failure",
                    "agent_id": agent_id,
                    "error": payload.get("error", ""),
                }, ts=ts)
                self.snapshot(force=True)
            elif kind_value == "escalation":
                self.append_event({
                    "event": "escalation",
                    "agent_id": agent_id,
                    "issue": payload.get("issue", ""),
                }, ts=ts)
                self.snapshot(force=True)
            else:
                # Activity: keep the tree fresh while work progresses
                # (throttled), not only on terminal events.
                self.append_event({
                    "event": "activity",
                    "agent_id": agent_id,
                    "event_type": kind_value,
                    "data": payload,
                }, ts=ts)
                self.snapshot()

        # Prefer the real EventBus's global subscription; fall back to the
        # runtime's topic-based bus contract (publish/drain) by polling.
        subscribe_global = getattr(bus, "subscribe_global", None)
        if subscribe_global is not None:
            subscribe_global(on_event)
        else:
            self._poll_events(runtime, on_event)
        self.snapshot(force=True)

    def _poll_events(self, runtime: Any, on_event: Any) -> None:
        """Poll the runtime's topic-based bus (``events:<agent_id>``) for events.

        Used when the bus exposes only ``publish(topic, event)`` /
        ``drain(topic)`` (the runtime's in-memory default). A daemon thread
        reads each agent's event topic and forwards to *on_event*. The bus
        peek is non-destructive (the drain-race fix), so this thread keeps
        its own per-agent cursor and forwards each event exactly once.
        """
        import threading

        # agent_id -> number of events already forwarded (this writer's
        # watermark over the non-destructive stream).
        cursors: dict[str, int] = {}

        def _poll() -> None:
            while True:
                try:
                    agents = getattr(runtime, "_agents", None)
                    if agents is not None:
                        for agent_id in list(agents.keys()):
                            topic = f"events:{agent_id}"
                            peek = getattr(runtime.event_bus, "peek", None)
                            if peek is not None:
                                events = peek(topic)
                                seen = cursors.get(agent_id, 0)
                                if len(events) < seen:
                                    # The stream shrank underneath us (a
                                    # foreign destructive drain): re-read
                                    # from the start rather than skip.
                                    seen = 0
                                for event in events[seen:]:
                                    on_event(event)
                                cursors[agent_id] = len(events)
                            else:
                                # A bus without the fan-out seam: the
                                # destructive drain forwards each event once.
                                for event in runtime.event_bus.drain(topic):
                                    on_event(event)
                except Exception:  # noqa: BLE001 - polling must never crash
                    pass
                time.sleep(0.05)

        thread = threading.Thread(
            target=_poll, name="dhc-state-poll", daemon=True
        )
        thread.start()
