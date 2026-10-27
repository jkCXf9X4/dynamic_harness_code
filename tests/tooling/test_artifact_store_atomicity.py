"""Atomicity, locking, and metadata-immutability tests for ArtifactStore.

Covers vision C6 (artifact immutability is a hard commitment) and the audit
trail: a crash never leaves a torn body, concurrent publishers of one id
converge on a single body, id verification rejects forgeries, and the
``headline``/``summary`` index metadata is set exactly once.
"""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

import pytest

from dhc.data.models import Artifact
from dhc.tooling import ArtifactStore
from dhc.tooling import artifact_store as store_mod


def make_artifact(headline: str, summary: str, report) -> Artifact:
    return Artifact(headline=headline, summary=summary, report=report)


def read_conflicts(root) -> list[dict]:
    path = root / "metadata-conflicts.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


# --------------------------------------------------------------------------- #
# 1. Atomic body writes
# --------------------------------------------------------------------------- #


def test_atomic_write_keeps_old_file_when_replace_fails(tmp_path, monkeypatch):
    """A failure at the publish step must leave the previous body intact."""

    body = tmp_path / "body.json"
    body.write_text("old body", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("injected replace failure")

    monkeypatch.setattr(store_mod.os, "replace", boom)
    with pytest.raises(OSError, match="injected replace failure"):
        store_mod._atomic_write_text(body, "new body")

    assert body.read_text(encoding="utf-8") == "old body"
    assert list(tmp_path.iterdir()) == [body]  # no leftover temp file


def test_put_body_failure_is_torn_write_free(tmp_path, monkeypatch):
    """fsync failure mid-body-write leaves no partial body and no index entry."""
    store = ArtifactStore(tmp_path)
    first = make_artifact("h1", "s1", {"x": 1})
    first_id = store.put(first)

    def boom(fd):
        raise OSError("injected fsync failure")

    monkeypatch.setattr(store_mod.os, "fsync", boom)
    second = make_artifact("h2", "s2", {"x": 2})
    with pytest.raises(OSError, match="injected fsync failure"):
        store.put(second)
    monkeypatch.undo()

    assert not (tmp_path / "artifacts" / f"{second.id}.json").exists()
    assert list(tmp_path.rglob("*.tmp")) == []
    reopened = ArtifactStore(tmp_path)
    assert reopened.list_ids() == [first_id]
    assert reopened.get_report(first_id) == {"x": 1}


def test_index_failure_preserves_previous_index(tmp_path, monkeypatch):
    store = ArtifactStore(tmp_path)
    first_id = store.put(make_artifact("h1", "s1", "one"))
    index_path = tmp_path / "index.json"
    before = index_path.read_text(encoding="utf-8")

    real_replace = os.replace

    def selective_replace(src, dst):
        if str(dst).endswith("index.json"):
            raise OSError("injected index failure")
        return real_replace(src, dst)

    monkeypatch.setattr(store_mod.os, "replace", selective_replace)
    with pytest.raises(OSError, match="injected index failure"):
        store.put(make_artifact("h2", "s2", "two"))
    monkeypatch.undo()

    assert index_path.read_text(encoding="utf-8") == before
    assert ArtifactStore(tmp_path).list_ids() == [first_id]


# --------------------------------------------------------------------------- #
# 2. Concurrent writers
# --------------------------------------------------------------------------- #


def test_two_threads_same_id_converge(tmp_path):
    """N threads with independent stores publish one body; 1 metadata winner."""
    workers = 8
    barrier = threading.Barrier(workers)
    ids: list[str] = []
    ids_lock = threading.Lock()

    def publish(n: int) -> None:
        store = ArtifactStore(tmp_path)  # own instance => own flock fd
        art = make_artifact(f"head-{n}", f"sum-{n}", {"shared": 1})
        barrier.wait()
        aid = store.put(art)
        with ids_lock:
            ids.append(aid)

    threads = [threading.Thread(target=publish, args=(n,)) for n in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(set(ids)) == 1
    aid = ids[0]
    bodies = list((tmp_path / "artifacts").glob("*.json"))
    assert len(bodies) == 1
    assert bodies[0].name == f"{aid}.json"

    reopened = ArtifactStore(tmp_path)
    assert reopened.count() == 1
    assert reopened.get_report(aid) == {"shared": 1}
    assert reopened.get_headline(aid) in {f"head-{n}" for n in range(workers)}

    conflicts = read_conflicts(tmp_path)
    assert len(conflicts) == workers - 1
    assert {c["reason"] for c in conflicts} == {"immutable_metadata"}


def _publish_in_process(args: tuple[str, int]) -> str:
    root, n = args
    store = ArtifactStore(root)
    return store.put(make_artifact(f"proc-{n}", f"proc-sum-{n}", {"body": "same"}))


def test_two_processes_same_id_converge(tmp_path):
    """Cross-process serialisation via fcntl.flock: one body, one winner."""
    workers = 4
    with ProcessPoolExecutor(
        max_workers=workers, mp_context=get_context("fork")
    ) as pool:
        ids = list(pool.map(_publish_in_process, [(str(tmp_path), n) for n in range(workers)]))

    assert len(set(ids)) == 1
    aid = ids[0]
    assert len(list((tmp_path / "artifacts").glob("*.json"))) == 1
    index = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    assert list(index) == [aid]
    assert len(read_conflicts(tmp_path)) == workers - 1

    reopened = ArtifactStore(tmp_path)
    assert reopened.get_report(aid) == {"body": "same"}


# --------------------------------------------------------------------------- #
# 3. Id verification
# --------------------------------------------------------------------------- #


def test_mismatched_id_rejected_and_nothing_written(tmp_path):
    store = ArtifactStore(tmp_path)
    legit = make_artifact("h", "s", {"x": 1})
    aid = store.put(legit)

    forged = Artifact.model_construct(
        id=aid, headline="h", summary="s", report={"x": 999}
    )
    with pytest.raises(ValueError, match="does not match content hash"):
        store.put(forged)

    assert store.list_ids() == [aid]
    assert ArtifactStore(tmp_path).get_report(aid) == {"x": 1}


# --------------------------------------------------------------------------- #
# 4. Set-once metadata
# --------------------------------------------------------------------------- #


def test_republish_does_not_change_metadata(tmp_path):
    store = ArtifactStore(tmp_path)
    first = make_artifact("original headline", "original summary", {"x": 1})
    aid = store.put(first)

    second = make_artifact("mutated headline", "mutated summary", {"x": 1})
    assert store.put(second) == aid

    assert store.get_headline(aid) == "original headline"
    assert store.get_summary(aid) == "original summary"

    # Reopen: the disk index agrees with the in-memory one.
    reopened = ArtifactStore(tmp_path)
    assert reopened.get_headline(aid) == "original headline"
    assert reopened.get_summary(aid) == "original summary"

    conflicts = read_conflicts(tmp_path)
    assert len(conflicts) == 1
    record = conflicts[0]
    assert record["id"] == aid
    assert record["reason"] == "immutable_metadata"
    assert record["fields"] == ["headline", "summary"]
    assert record["stored"] == {
        "headline": "original headline",
        "summary": "original summary",
    }
    assert record["incoming"] == {
        "headline": "mutated headline",
        "summary": "mutated summary",
    }


def test_republish_matching_metadata_is_silent(tmp_path):
    store = ArtifactStore(tmp_path)
    art = make_artifact("h", "s", {"x": 1})
    aid = store.put(art)
    assert store.put(make_artifact("h", "s", {"x": 1})) == aid
    assert read_conflicts(tmp_path) == []
    assert store.metadata_conflicts_path == tmp_path / "metadata-conflicts.jsonl"
