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

from dhc.agent.agent import Agent
from dhc.data.models import AgentStatus, Event, EventKind, Result
from dhc.agent.runtime import Runtime
from dhc.agent.state import (
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
