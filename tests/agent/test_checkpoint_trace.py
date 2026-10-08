"""Tests for dhc.checkpoint and dhc.trace — peripheral persistence wrappers.

Covers the CheckpointStore save/load/list roundtrip, atomic + best-effort
writes, the CheckpointDriver before/after save semantics, the TraceStore
append/read roundtrip for all entry types, and the TracingEngine wrapper
around a real ReplEngine.execute.
"""

import json
import os
import stat

import pytest

from dhc.agent.checkpoint import AgentCheckpoint, CheckpointDriver, CheckpointStore
from dhc.data.models import Result
from dhc.agent.repl import ReplEngine
from dhc.data.trace import ENTRY_TYPES, TraceStore, TracingEngine


# --------------------------------------------------------------------------- #
# CheckpointStore
# --------------------------------------------------------------------------- #


def test_checkpoint_store_roundtrip(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")
    cp = AgentCheckpoint(
        agent_id="a1",
        requirement="do the thing",
        acceptance=["it works", "it is fast"],
        status="running",
        turn_counter=3,
        checkpoint_notes=["before turn 3", "after turn 3"],
        updated_at="2026-01-01T00:00:00+00:00",
        extra={"driver": "MockDriver"},
    )
    path = store.save(cp)

    assert path == store.root / "a1.json"
    assert path.exists()
    # Written via model_dump_json(indent=2) — pretty-printed JSON.
    raw = path.read_text(encoding="utf-8")
    assert '"agent_id": "a1"' in raw
    assert "\n" in raw

    loaded = store.load("a1")
    assert loaded is not None
    assert loaded.agent_id == "a1"
    assert loaded.requirement == "do the thing"
    assert loaded.acceptance == ["it works", "it is fast"]
    assert loaded.status == "running"
    assert loaded.turn_counter == 3
    assert loaded.checkpoint_notes == ["before turn 3", "after turn 3"]
    assert loaded.extra == {"driver": "MockDriver"}

    assert store.list_ids() == ["a1"]


def test_checkpoint_store_load_missing_returns_none(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")
    assert store.load("nope") is None
    assert store.list_ids() == []


def test_checkpoint_store_save_is_atomic(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")
    cp = AgentCheckpoint(agent_id="a1", turn_counter=1)
    store.save(cp)
    # No leftover tmp files after an atomic save.
    leftovers = [p for p in store.root.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_checkpoint_store_save_best_effort_readonly_root(tmp_path):
    root = tmp_path / "ro"
    root.mkdir()
    os.chmod(root, stat.S_IRUSR | stat.S_IXUSR)  # read-only (no write bit)
    try:
        store = CheckpointStore(root)
        cp = AgentCheckpoint(agent_id="a1", turn_counter=1)
        # Must not raise even though the write cannot succeed.
        store.save(cp)
    finally:
        os.chmod(root, stat.S_IRWXU)  # restore so tmp_path cleanup works


# --------------------------------------------------------------------------- #
# CheckpointDriver
# --------------------------------------------------------------------------- #


class _FakeAgent:
    def __init__(self, agent_id="a1"):
        self.id = agent_id
        self.requirement = "req"
        self.acceptance = ("acc",)
        self._status = "running"


def test_checkpoint_driver_saves_before_and_after(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")
    calls = []

    def driver(agent):
        calls.append(agent.id)
        return "print(1)"

    wrapped = CheckpointDriver(driver, store, interval=1)
    agent = _FakeAgent()

    out = wrapped(agent)
    assert out == "print(1)"
    assert calls == ["a1"]

    cp = store.load("a1")
    assert cp is not None
    # turn_counter incremented once per call; both before and after saved.
    assert cp.turn_counter == 1
    assert any("before turn 1" in n for n in cp.checkpoint_notes)
    assert any("after turn 1" in n for n in cp.checkpoint_notes)

    wrapped(agent)
    cp2 = store.load("a1")
    assert cp2 is not None
    assert cp2.turn_counter == 2
    assert any("before turn 2" in n for n in cp2.checkpoint_notes)
    assert any("after turn 2" in n for n in cp2.checkpoint_notes)


def test_checkpoint_driver_resumes_counter_from_store(tmp_path):
    store = CheckpointStore(tmp_path / "checkpoints")
    store.save(AgentCheckpoint(agent_id="a1", turn_counter=5))
    wrapped = CheckpointDriver(lambda agent: None, store, interval=1)
    wrapped(_FakeAgent())
    cp = store.load("a1")
    assert cp is not None
    assert cp.turn_counter == 6


def test_checkpoint_driver_best_effort_store_failure(tmp_path):
    root = tmp_path / "ro"
    root.mkdir()
    os.chmod(root, stat.S_IRUSR | stat.S_IXUSR)
    try:
        store = CheckpointStore(root)
        wrapped = CheckpointDriver(lambda agent: "print(1)", store, interval=1)
        # Driver loop must not break even though saves fail.
        assert wrapped(_FakeAgent()) == "print(1)"
    finally:
        os.chmod(root, stat.S_IRWXU)


# --------------------------------------------------------------------------- #
# TraceStore
# --------------------------------------------------------------------------- #


def test_trace_store_append_read_all_entry_types(tmp_path):
    store = TraceStore(tmp_path / "traces")
    assert store.path_for("a1") == store.root / "a1" / "trace.jsonl"

    samples = {
        "llm_request": {"messages": [{"role": "user", "content": "hi"}]},
        "llm_response": {"content": "hello", "model": "mock"},
        "tool_call": {"name": "bash", "arguments": {"command": "ls"}},
        "tool_result": {"name": "bash", "content_preview": "out"},
        "event": {"event": "spawned", "parent_id": "root"},
    }
    for entry_type, data in samples.items():
        store.append("a1", entry_type, data)

    entries = store.read("a1")
    assert len(entries) == 5
    assert [e["type"] for e in entries] == list(samples.keys())
    for entry, (entry_type, data) in zip(entries, samples.items()):
        assert entry["type"] == entry_type
        assert entry["ts"] > 0
        assert entry["timestamp"]
        for key, value in data.items():
            assert entry[key] == value

    # Append-only: reading again returns the same entries, and a new append
    # extends rather than truncates.
    store.append("a1", "event", {"event": "done"})
    assert len(store.read("a1")) == 6


def test_trace_store_isolates_agents(tmp_path):
    store = TraceStore(tmp_path / "traces")
    store.append("a1", "event", {"event": "x"})
    store.append("a2", "event", {"event": "y"})
    assert [e["event"] for e in store.read("a1")] == ["x"]
    assert [e["event"] for e in store.read("a2")] == ["y"]


def test_trace_store_best_effort_readonly_root(tmp_path):
    root = tmp_path / "ro"
    root.mkdir()
    os.chmod(root, stat.S_IRUSR | stat.S_IXUSR)
    try:
        store = TraceStore(root)
        # Must not raise even though the write cannot succeed.
        store.append("a1", "event", {"event": "x"})
        assert store.read("a1") == []
    finally:
        os.chmod(root, stat.S_IRWXU)


def test_trace_store_entry_types_constant():
    assert ENTRY_TYPES == {
        "llm_request",
        "llm_response",
        "tool_call",
        "tool_result",
        "event",
    }


# --------------------------------------------------------------------------- #
# TracingEngine
# --------------------------------------------------------------------------- #


def test_tracing_engine_records_around_repl_execute(tmp_path):
    store = TraceStore(tmp_path / "traces")
    engine = ReplEngine()
    tracing = TracingEngine(engine, store)

    result = tracing.execute(
        "a1",
        "x = 41\nresult = Result(done=True, ok=True, value=x + 1)",
        namespace={"Result": Result},
    )

    # Returns the wrapped result unchanged.
    assert isinstance(result, Result)
    assert result.ok is True
    assert result.value == 42

    entries = store.read("a1")
    assert [e["type"] for e in entries] == ["tool_call", "tool_result"]
    tool_call = entries[0]
    assert tool_call["agent_id"] == "a1"
    assert "x = 41" in tool_call["code"]
    tool_result = entries[1]
    assert tool_result["ok"] is True
    assert tool_result["done"] is True
    assert tool_result["duration_ms"] >= 0


def test_tracing_engine_passes_namespace_and_timeout(tmp_path):
    store = TraceStore(tmp_path / "traces")
    engine = ReplEngine()
    tracing = TracingEngine(engine, store)

    result = tracing.execute(
        "a1",
        "result = Result(done=True, ok=True, value=helper)",
        namespace={"helper": 7, "Result": Result},
        timeout=5.0,
    )
    assert result.value == 7
    entries = store.read("a1")
    assert "helper" in entries[0]["namespace_keys"]
    assert entries[0]["timeout"] == 5.0


def test_tracing_engine_records_failed_result(tmp_path):
    store = TraceStore(tmp_path / "traces")
    engine = ReplEngine()
    tracing = TracingEngine(engine, store)

    result = tracing.execute("a1", "raise ValueError('boom')")
    assert result.ok is False
    assert "ValueError" in result.reason

    entries = store.read("a1")
    assert [e["type"] for e in entries] == ["tool_call", "tool_result"]
    assert entries[1]["ok"] is False
    assert "ValueError" in entries[1]["reason"]


def test_tracing_engine_best_effort_store_failure(tmp_path):
    root = tmp_path / "ro"
    root.mkdir()
    os.chmod(root, stat.S_IRUSR | stat.S_IXUSR)
    try:
        store = TraceStore(root)
        engine = ReplEngine()
        tracing = TracingEngine(engine, store)
        # Engine loop must not break even though tracing fails.
        result = tracing.execute(
            "a1",
            "result = Result(done=True, ok=True, value=1)",
            namespace={"Result": Result},
        )
        assert result.ok is True
        assert result.value == 1
    finally:
        os.chmod(root, stat.S_IRWXU)