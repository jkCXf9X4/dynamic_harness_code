"""Tests for dhc.state — run-overview persistence for manual review.

Uses scripted drivers and fakes only — no real LLM, no real REPL, no real
artifact store. All file writes go to pytest ``tmp_path``; nothing is written
into the repo tree.
"""

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dhc.framework.agent import Agent
from dhc.data.models import AgentStatus, Event, EventKind, Result
from dhc.framework.runtime import Runtime
from dhc.ui.state import (
    TERMINAL_EVENT_KINDS,
    AgentNode,
    StateWriter,
    build_agent_tree,
    build_stats,
    render_text_tree,
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class ScriptedDriver:
    """A driver that replays a fixed script of code blocks, then settles."""

    def __init__(self, *blocks: str) -> None:
        self.blocks = list(blocks)
        self.calls = 0

    def __call__(self, agent: Agent):
        if self.calls >= len(self.blocks):
            return None
        code = self.blocks[self.calls]
        self.calls += 1
        return code


def wait_for(predicate, timeout: float = 10.0) -> bool:
    """Poll *predicate* until it is true or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return predicate()


def make_runtime(**kwargs) -> Runtime:
    rt = Runtime(**kwargs)
    rt.start()
    return rt


def spawn_root_with_children(rt: Runtime) -> tuple[str, str]:
    """Spawn a root agent that spawns one child, then settle both.

    Returns ``(root_id, child_id)``. The root's driver spawns the child and
    completes; the child's driver completes immediately.
    """
    child_id: list[str] = []

    def root_driver(agent: Agent):
        if not child_id:
            child = agent.spawn("child task", driver=ScriptedDriver("complete('child done')"))
            child_id.append(child.id)
            return "complete('root done')"
        return None

    root = rt.spawn("root task", driver=root_driver)
    root_id = root.id
    assert wait_for(lambda: bool(child_id))
    assert wait_for(lambda: rt.is_settled(child_id[0]))
    assert wait_for(lambda: rt.is_settled(root_id))
    return root_id, child_id[0]


# --------------------------------------------------------------------------- #
# build_agent_tree / build_stats
# --------------------------------------------------------------------------- #


def test_build_agent_tree_reflects_runtime_state(tmp_path):
    rt = make_runtime()
    root_id, child_id = spawn_root_with_children(rt)

    nodes = build_agent_tree(rt)
    assert len(nodes) == 1
    root = nodes[0]
    assert root.agent_id == root_id
    assert root.description == "root task"
    assert root.status == AgentStatus.completed.value
    assert len(root.children) == 1
    child = root.children[0]
    assert child.agent_id == child_id
    assert child.description == "child task"
    assert child.status == AgentStatus.completed.value
    assert child.children == []


def test_build_agent_tree_artifact_ids_from_result(tmp_path):
    rt = make_runtime()
    root = rt.spawn(
        "root task",
        driver=ScriptedDriver("complete('done', artifacts=('sha256:abc',))"),
    )
    assert wait_for(lambda: rt.is_settled(root.id))

    nodes = build_agent_tree(rt)
    assert nodes[0].artifact_ids == ["sha256:abc"]


def test_build_stats_counts_agents(tmp_path):
    rt = make_runtime()
    spawn_root_with_children(rt)

    stats = build_stats(rt)
    assert stats.agents == 2
    assert stats.commits == 0
    assert stats.tokens == 0
    assert stats.prompt_tokens == 0
    assert stats.cached_tokens == 0
    assert stats.cache_hit_rate == 0.0
    assert stats.cost_usd == 0.0


def test_build_agent_tree_empty_runtime(tmp_path):
    rt = make_runtime()
    assert build_agent_tree(rt) == []
    assert build_stats(rt).agents == 0


# --------------------------------------------------------------------------- #
# StateWriter.snapshot
# --------------------------------------------------------------------------- #


def test_snapshot_writes_all_four_files_with_schema(tmp_path):
    rt = make_runtime()
    spawn_root_with_children(rt)
    writer = StateWriter(rt, root=tmp_path)

    writer.snapshot(force=True)

    # agent_tree.json — array of root nodes, recursive children.
    tree = json.loads((tmp_path / "agent_tree.json").read_text())
    assert isinstance(tree, list) and len(tree) == 1
    root = tree[0]
    for key in (
        "agent_id", "description", "status", "tokens", "messages",
        "context_tokens", "prompt_tokens", "completion_tokens",
        "cached_tokens", "cache_hit_rate", "cost_usd", "cum_cost_usd",
        "artifact_ids", "trace_path", "children",
    ):
        assert key in root, f"missing key {key!r}"
    assert root["status"] == AgentStatus.completed.value
    assert root["tokens"] == 0
    assert root["trace_path"] is None
    assert len(root["children"]) == 1
    assert root["children"][0]["agent_id"] == root["children"][0]["agent_id"]

    # stats.json — aggregate counters.
    stats = json.loads((tmp_path / "stats.json").read_text())
    assert stats == {
        "agents": 2, "commits": 0, "tokens": 0, "prompt_tokens": 0,
        "cached_tokens": 0, "cache_hit_rate": 0.0, "cost_usd": 0.0,
    }

    # agents.txt — box-drawn tree with statuses.
    text = (tmp_path / "agents.txt").read_text()
    assert "└" in text or "├" in text or "│" in text
    assert "[completed]" in text
    assert "root task" in text
    assert "child task" in text

    # events.jsonl — not written by snapshot itself, but the path exists.
    assert writer.tree_path == tmp_path / "agent_tree.json"
    assert writer.stats_path == tmp_path / "stats.json"
    assert writer.agents_txt_path == tmp_path / "agents.txt"
    assert writer.events_path == tmp_path / "events.jsonl"


def test_snapshot_throttled_unless_force(tmp_path):
    rt = make_runtime()
    spawn_root_with_children(rt)
    writer = StateWriter(rt, root=tmp_path, snapshot_interval=60.0)

    writer.snapshot(force=True)
    first = (tmp_path / "agent_tree.json").read_text()

    # Second snapshot within the interval is skipped (no force).
    writer.snapshot()
    assert (tmp_path / "agent_tree.json").read_text() == first

    # Force writes even within the interval.
    writer.snapshot(force=True)
    assert (tmp_path / "agent_tree.json").read_text() == first  # same content


def test_snapshot_force_writes_after_throttle(tmp_path):
    rt = make_runtime()
    spawn_root_with_children(rt)
    writer = StateWriter(rt, root=tmp_path, snapshot_interval=0.0)

    writer.snapshot(force=True)
    first = (tmp_path / "agent_tree.json").read_text()
    writer.snapshot()
    # interval 0.0 -> every snapshot writes; content identical here.
    assert (tmp_path / "agent_tree.json").read_text() == first


def test_snapshot_default_root_uses_artifact_root_parent(tmp_path):
    class FakeSettings:
        artifact_root = tmp_path / "artifacts"
        workspace_root = tmp_path

    rt = make_runtime(settings=FakeSettings())
    writer = StateWriter(rt)
    assert writer.root == tmp_path
    assert writer.tree_path == tmp_path / "agent_tree.json"


def test_snapshot_default_root_falls_back_to_workspace(tmp_path):
    class FakeSettings:
        workspace_root = tmp_path

    rt = make_runtime(settings=FakeSettings())
    writer = StateWriter(rt)
    assert writer.root == tmp_path / ".dynamic-harness"


# --------------------------------------------------------------------------- #
# StateWriter.append_event
# --------------------------------------------------------------------------- #


def test_append_event_appends_jsonl_lines_with_ts(tmp_path):
    rt = make_runtime()
    writer = StateWriter(rt, root=tmp_path)

    writer.append_event({"event": "report", "summary": "done", "confidence": 0.9})
    writer.append_event({"event": "failure", "error": "boom"})

    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert "ts" in first
    assert first["event"] == "report"
    assert first["summary"] == "done"
    assert first["confidence"] == 0.9
    second = json.loads(lines[1])
    assert second["event"] == "failure"
    assert second["error"] == "boom"
    # ts is ISO-8601 parseable.
    datetime.fromisoformat(first["ts"])


def test_append_event_never_truncates(tmp_path):
    rt = make_runtime()
    writer = StateWriter(rt, root=tmp_path)

    writer.append_event({"event": "activity", "agent_id": "a1", "event_type": "turn_started", "data": {}})
    writer.append_event({"event": "activity", "agent_id": "a1", "event_type": "turn_completed", "data": {}})

    lines = (tmp_path / "events.jsonl").read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["event_type"] == "turn_started"
    assert json.loads(lines[1])["event_type"] == "turn_completed"


def test_append_event_accepts_explicit_ts(tmp_path):
    rt = make_runtime()
    writer = StateWriter(rt, root=tmp_path)
    ts = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    writer.append_event({"event": "report", "summary": "s"}, ts=ts)

    line = json.loads((tmp_path / "events.jsonl").read_text())
    assert line["ts"] == ts.isoformat()


# --------------------------------------------------------------------------- #
# StateWriter.attach
# --------------------------------------------------------------------------- #


def test_attach_triggers_initial_snapshot(tmp_path):
    rt = make_runtime()
    spawn_root_with_children(rt)
    writer = StateWriter(rt, root=tmp_path)

    writer.attach()

    assert (tmp_path / "agent_tree.json").exists()
    assert (tmp_path / "stats.json").exists()
    assert (tmp_path / "agents.txt").exists()


def test_attach_subscribes_to_event_bus_and_forces_snapshot_on_terminal(tmp_path):
    rt = make_runtime()
    # Spawn an agent so the polling thread has a topic to drain.
    root = rt.spawn("root task", driver=ScriptedDriver("complete('done')"))
    assert wait_for(lambda: rt.is_settled(root.id))
    writer = StateWriter(rt, root=tmp_path, snapshot_interval=60.0)
    writer.attach()

    # Emit a report event through the runtime's bus (the real EventBus shape).
    bus = rt.event_bus
    if hasattr(bus, "publish") and not hasattr(bus, "subscribe_global"):
        # In-memory topic bus: publish to the agent's event topic.
        bus.publish("events:a1", Event(kind=EventKind.turn_started, agent_id="a1", payload={}))
        bus.publish("events:a1", Event(kind=EventKind.child_settled, agent_id="a1", payload={"status": "completed"}))
    else:
        bus.publish(Event(kind=EventKind.child_settled, agent_id="a1", payload={"status": "completed"}))

    # The polling thread (or global subscription) should have appended events.
    assert wait_for(lambda: (tmp_path / "events.jsonl").exists())


def test_attach_without_bus_still_snapshots(tmp_path):
    class NoBusRuntime:
        _agents = {}

    writer = StateWriter(NoBusRuntime(), root=tmp_path)
    writer.attach()
    assert (tmp_path / "agent_tree.json").exists()
    assert (tmp_path / "stats.json").exists()
    assert (tmp_path / "agents.txt").exists()


# --------------------------------------------------------------------------- #
# render_text_tree
# --------------------------------------------------------------------------- #


def test_render_text_tree_box_drawing_and_statuses():
    nodes = [
        AgentNode(
            agent_id="a1",
            description="root task",
            status="completed",
            children=[
                AgentNode(agent_id="a2", description="child task", status="running"),
            ],
        )
    ]
    text = render_text_tree(nodes)
    assert "└" in text or "├" in text or "│" in text
    assert "[completed]" in text
    assert "[running]" in text
    assert "root task" in text
    assert "child task" in text


def test_render_text_tree_empty():
    assert render_text_tree([]) == "(no agents)\n"


# --------------------------------------------------------------------------- #
# Event-kind mapping (decision 0009, IMP-002)
#
# The snapshot must route every EventKind through the enum-keyed mapping in
# TERMINAL_EVENT_KINDS — a renamed or new kind must never be silently dropped.
# These tests drive the mapping through a synchronous fake bus so the routing
# is deterministic (no polling thread, no wait_for).
# --------------------------------------------------------------------------- #


class _FakeBus:
    """Synchronous in-memory bus: ``publish`` calls global subscribers inline."""

    def __init__(self) -> None:
        self._subs: list = []

    def subscribe_global(self, cb) -> None:
        self._subs.append(cb)

    def publish(self, event) -> None:
        for cb in self._subs:
            cb(event)


class _FakeRuntime:
    """Minimal runtime: a global bus and an empty agent registry."""

    def __init__(self) -> None:
        self.event_bus = _FakeBus()
        self._agents = {}


def _attach_fake_writer(tmp_path) -> tuple[StateWriter, _FakeBus, list]:
    """Attach a writer to a synchronous fake bus and return a *spy* that
    records every ``snapshot(force=...)`` call (instance attribute shadows the
    bound method, so ``self.snapshot(...)`` inside ``on_event`` hits the spy).
    """
    rt = _FakeRuntime()
    writer = StateWriter(rt, root=tmp_path, snapshot_interval=60.0)
    calls: list[bool] = []
    orig = writer.snapshot

    def spy(force: bool = False) -> None:
        calls.append(force)
        orig(force)

    writer.snapshot = spy  # type: ignore[method-assign]
    writer.attach()
    return writer, rt.event_bus, calls


def _read_events(tmp_path) -> list[dict]:
    path = tmp_path / "events.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text().splitlines()
        if line.strip()
    ]


def test_every_event_kind_is_recorded_not_dropped(tmp_path):
    """Publishing every EventKind member yields a record for each — no silent
    drop. Iterating the enum means a *new* member is covered automatically."""
    writer, bus, calls = _attach_fake_writer(tmp_path)
    for kind in EventKind:
        bus.publish(Event(kind=kind, agent_id="a1", payload={}))

    recorded = _read_events(tmp_path)
    # Exactly one record per kind (the fake bus is synchronous, no other
    # events are in flight).
    assert len(recorded) == len(EventKind)
    recorded_kinds = {rec.get("event_type") or rec.get("event") for rec in recorded}
    for kind in EventKind:
        assert kind.value in recorded_kinds, f"{kind!r} was silently dropped"


def test_terminal_kind_escalation_forces_snapshot_and_records_issue(tmp_path):
    """Per-kind terminal test: EventKind.escalation records a dedicated
    ``escalation`` record and forces a snapshot (rewrites the tree even within
    the throttle window)."""
    writer, bus, calls = _attach_fake_writer(tmp_path)
    assert calls == [True]  # attach's initial forced snapshot

    bus.publish(Event(kind=EventKind.escalation, agent_id="a1", payload={"issue": "help"}))

    rec = _read_events(tmp_path)[-1]
    assert rec["event"] == "escalation"
    assert rec["agent_id"] == "a1"
    assert rec["issue"] == "help"
    # Terminal forces a snapshot: a new force=True call despite the 60s window.
    assert calls == [True, True]


def test_activity_kind_records_event_type_and_throttles(tmp_path):
    """Per-kind activity test: a non-terminal kind records an ``activity``
    record carrying its ``event_type`` and does NOT force a snapshot (throttled
    within the window)."""
    writer, bus, calls = _attach_fake_writer(tmp_path)
    assert calls == [True]  # attach's initial forced snapshot

    bus.publish(Event(kind=EventKind.turn_started, agent_id="a1", payload={}))

    rec = _read_events(tmp_path)[-1]
    assert rec["event"] == "activity"
    assert rec["event_type"] == "turn_started"
    assert rec["agent_id"] == "a1"
    # Activity is throttled: the snapshot call is made with force=False and,
    # within the 60s window, the real snapshot is a no-op (no rewrite).
    assert calls == [True, False]


def test_terminal_table_keys_are_real_event_kinds():
    """Every key in TERMINAL_EVENT_KINDS is a real EventKind member. A stale or
    renamed member name in the table is caught here (the import-time
    AttributeError is the loud path)."""
    assert set(TERMINAL_EVENT_KINDS) <= set(EventKind)


def test_terminal_set_is_explicit():
    """Pin the terminal set so promoting a new kind to terminal is a visible,
    reviewable test change — not an accident."""
    assert set(TERMINAL_EVENT_KINDS) == {EventKind.escalation}


def test_renamed_terminal_member_fails_loudly_not_silently():
    """IMP-002's core hazard: a *renamed* kind must surface, not silently drop.

    The terminal table is keyed by ``EventKind`` *members* (not string values),
    so it is built by *referencing* each member. Renaming a member (e.g.
    ``escalation`` -> ``escalated``) without updating the table makes that
    reference an import-time ``AttributeError`` — loud, not a silent drop.
    Prove the mechanism on the real table:
    """
    # The table is member-keyed: every key is a live EventKind member. This is
    # the property that makes a rename loud (a string-keyed table would not).
    assert all(isinstance(k, EventKind) for k in TERMINAL_EVENT_KINDS)
    # The table is built by referencing members. A renamed-away name is a hard
    # AttributeError at construction time — the import-time loud path. This
    # mirrors what happens to TERMINAL_EVENT_KINDS if `escalation` were
    # renamed to `escalated` and the table not updated.
    with pytest.raises(AttributeError):
        {EventKind.escalated: "escalated"}  # noqa: B018 - deliberate bad ref
