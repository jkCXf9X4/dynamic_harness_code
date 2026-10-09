"""Tests for dhc.tooling.artifact_store: ArtifactStore and BoundaryEventLog.

All tests use pytest's tmp_path fixture for the store root — nothing is ever
written into the repository tree.
"""

from __future__ import annotations

import json

import pytest

from dhc.tooling import BOUNDARY_EVENT_KINDS, ArtifactStore, BoundaryEventLog
from dhc.errors import ArtifactNotFoundError
from dhc.data.models import Artifact


def make_artifact(headline: str, summary: str, report) -> Artifact:
    return Artifact(headline=headline, summary=summary, report=report)


# --------------------------------------------------------------------------- #
# ArtifactStore: put/get roundtrip
# --------------------------------------------------------------------------- #


def test_put_get_roundtrip(tmp_path):
    store = ArtifactStore(tmp_path)
    art = make_artifact("head", "sum", {"a": 1, "b": [1, 2, 3]})
    aid = store.put(art)

    assert aid == art.id
    assert aid.startswith("sha256:")
    assert store.exists(aid)
    assert store.count() == 1
    assert store.list_ids() == [aid]

    got = store.get(aid)
    assert got.id == aid
    assert got.headline == "head"
    assert got.summary == "sum"
    assert got.report == {"a": 1, "b": [1, 2, 3]}


def test_put_get_roundtrip_string_report(tmp_path):
    store = ArtifactStore(tmp_path)
    art = make_artifact("h", "s", "plain text body")
    aid = store.put(art)
    assert store.get(aid).report == "plain text body"


def test_get_missing_raises(tmp_path):
    store = ArtifactStore(tmp_path)
    with pytest.raises(ArtifactNotFoundError):
        store.get("sha256:" + "0" * 64)
    with pytest.raises(ArtifactNotFoundError):
        store.get_headline("sha256:" + "0" * 64)
    with pytest.raises(ArtifactNotFoundError):
        store.get_summary("sha256:" + "0" * 64)
    with pytest.raises(ArtifactNotFoundError):
        store.get_report("sha256:" + "0" * 64)


# --------------------------------------------------------------------------- #
# Content addressing / dedupe / immutability
# --------------------------------------------------------------------------- #


def test_same_body_same_id_dedupe(tmp_path):
    store = ArtifactStore(tmp_path)
    a1 = make_artifact("h1", "s1", {"x": 1})
    a2 = make_artifact("h2", "s2", {"x": 1})  # same body, different meta

    id1 = store.put(a1)
    id2 = store.put(a2)

    assert id1 == id2
    assert store.count() == 1
    # First write wins for the metadata tiers.
    assert store.get_headline(id1) == "h1"
    assert store.get_summary(id1) == "s1"


def test_put_twice_idempotent(tmp_path):
    store = ArtifactStore(tmp_path)
    art = make_artifact("h", "s", {"x": 1})
    id1 = store.put(art)
    id2 = store.put(art)
    assert id1 == id2
    assert store.count() == 1


def test_different_body_same_id_raises(tmp_path):
    store = ArtifactStore(tmp_path)
    a1 = make_artifact("h", "s", {"x": 1})
    id1 = store.put(a1)

    # Forge an artifact whose id claims to be id1 but whose body differs.
    # model_construct bypasses the pydantic validator so the store's own
    # content-address verification is what must reject it.
    forged = Artifact.model_construct(
        id=id1, headline="h", summary="s", report={"x": 2}
    )
    assert forged.id == id1
    with pytest.raises(ValueError):
        store.put(forged)


def test_put_rejects_non_artifact(tmp_path):
    store = ArtifactStore(tmp_path)
    with pytest.raises(TypeError):
        store.put({"headline": "h", "summary": "s", "report": {}})


# --------------------------------------------------------------------------- #
# Progressive disclosure tiers
# --------------------------------------------------------------------------- #


def test_progressive_disclosure_tiers(tmp_path):
    store = ArtifactStore(tmp_path)
    report = {"rows": [{"id": i, "value": f"v{i}"} for i in range(50)]}
    art = make_artifact("the headline", "the summary", report)
    aid = store.put(art)

    assert store.get_headline(aid) == "the headline"
    assert store.get_summary(aid) == "the summary"
    assert store.get_report(aid) == report
    assert store.get(aid).report == report


# --------------------------------------------------------------------------- #
# Persistence across store instances
# --------------------------------------------------------------------------- #


def test_persistence_across_reopen(tmp_path):
    store1 = ArtifactStore(tmp_path)
    a1 = make_artifact("h1", "s1", {"x": 1})
    a2 = make_artifact("h2", "s2", "body two")
    id1 = store1.put(a1)
    id2 = store1.put(a2)

    store2 = ArtifactStore(tmp_path)  # reopen: reload index from disk
    assert store2.count() == 2
    assert store2.list_ids() == sorted([id1, id2])
    assert store2.get_headline(id1) == "h1"
    assert store2.get_summary(id2) == "s2"
    assert store2.get_report(id1) == {"x": 1}
    assert store2.get_report(id2) == "body two"


def test_reopen_dedupe_still_works(tmp_path):
    store1 = ArtifactStore(tmp_path)
    id1 = store1.put(make_artifact("h", "s", {"x": 1}))

    store2 = ArtifactStore(tmp_path)
    id2 = store2.put(make_artifact("h", "s", {"x": 1}))
    assert id1 == id2
    assert store2.count() == 1


# --------------------------------------------------------------------------- #
# BoundaryEventLog
# --------------------------------------------------------------------------- #


def test_boundary_log_append_read(tmp_path):
    log = BoundaryEventLog(tmp_path)
    assert log.path == tmp_path / "boundary-events.jsonl"

    ev = log.append("spawned", "agent-1")
    assert ev["kind"] == "spawned"
    assert ev["agent_id"] == "agent-1"
    assert ev["causal_id"] is None
    assert ev["payload"] == {}
    assert "ts" in ev

    events = log.read()
    assert len(events) == 1
    assert events[0] == ev


def test_boundary_log_append_only(tmp_path):
    log = BoundaryEventLog(tmp_path)
    log.append("spawned", "a1")
    log.append("settled", "a1")
    events = log.read()
    assert [e["kind"] for e in events] == ["spawned", "settled"]
    # Append order preserved (oldest first).
    assert events[0]["ts"] <= events[1]["ts"]


def test_boundary_log_filter_by_agent(tmp_path):
    log = BoundaryEventLog(tmp_path)
    log.append("spawned", "a1")
    log.append("spawned", "a2")
    log.append("settled", "a1")

    a1_events = log.read(agent_id="a1")
    assert [e["agent_id"] for e in a1_events] == ["a1", "a1"]
    assert [e["kind"] for e in a1_events] == ["spawned", "settled"]

    a2_events = log.read(agent_id="a2")
    assert len(a2_events) == 1
    assert a2_events[0]["kind"] == "spawned"


def test_boundary_log_filter_by_kind(tmp_path):
    log = BoundaryEventLog(tmp_path)
    log.append("spawned", "a1")
    log.append("settled", "a1")
    log.append("published", "a1")

    spawned = log.read(kind="spawned")
    assert len(spawned) == 1
    assert spawned[0]["kind"] == "spawned"

    published = log.read(kind="published")
    assert len(published) == 1
    assert published[0]["kind"] == "published"


def test_boundary_log_filter_by_agent_and_kind(tmp_path):
    log = BoundaryEventLog(tmp_path)
    log.append("spawned", "a1")
    log.append("settled", "a1")
    log.append("spawned", "a2")

    events = log.read(agent_id="a1", kind="spawned")
    assert len(events) == 1
    assert events[0]["agent_id"] == "a1"
    assert events[0]["kind"] == "spawned"


def test_boundary_log_causal_id_linking(tmp_path):
    log = BoundaryEventLog(tmp_path)
    spawn = log.append("spawned", "child-1")
    settle = log.append("settled", "child-1", causal_id=spawn["ts"])

    events = log.read()
    assert events[1]["causal_id"] == events[0]["ts"]
    assert events[1]["kind"] == "settled"


def test_boundary_log_by_reference_payload(tmp_path):
    log = BoundaryEventLog(tmp_path)
    ev = log.append(
        "published",
        "agent-1",
        payload={"artifact_ids": ["sha256:abc"], "child_ids": ["child-9"]},
    )
    assert ev["payload"] == {
        "artifact_ids": ["sha256:abc"],
        "child_ids": ["child-9"],
    }
    # Payload is by-reference ids only — never full bodies.
    assert "report" not in ev["payload"]
    assert "body" not in ev["payload"]

    events = log.read()
    assert events[0]["payload"]["artifact_ids"] == ["sha256:abc"]


def test_boundary_log_unknown_kind_raises(tmp_path):
    log = BoundaryEventLog(tmp_path)
    with pytest.raises(ValueError):
        log.append("exploded", "a1")
    with pytest.raises(ValueError):
        log.read(kind="exploded")


def test_boundary_log_all_five_kinds(tmp_path):
    log = BoundaryEventLog(tmp_path)
    for kind in sorted(BOUNDARY_EVENT_KINDS):
        log.append(kind, "a1")
    kinds = {e["kind"] for e in log.read()}
    assert kinds == set(BOUNDARY_EVENT_KINDS)


def test_boundary_log_greppable_jsonl(tmp_path):
    log = BoundaryEventLog(tmp_path)
    log.append("spawned", "a1", payload={"child_ids": ["c1"]})
    raw = log.path.read_text(encoding="utf-8").strip().splitlines()
    assert len(raw) == 1
    parsed = json.loads(raw[0])
    assert parsed["kind"] == "spawned"
    assert parsed["agent_id"] == "a1"


def test_boundary_log_empty_read(tmp_path):
    log = BoundaryEventLog(tmp_path)
    assert log.read() == []
    assert log.read(agent_id="a1") == []
    assert log.read(kind="spawned") == []
