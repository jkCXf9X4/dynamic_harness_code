"""End-to-end integration tests: the REAL modules wired by build_runtime.

These tests exercise the fully-wired runtime (ReplEngine, EventBus +
BoundaryEventLog, CompletionDispatcher, ArtifactStore, communication
channels) with the deterministic MockDriver — no network, no API key.

Covered:

* full session: root -> publish -> fan-out -> aggregate -> settle
* terminal states and artifact ids present in the real store
* boundary event log has spawned/settled/published events with causal ids
* crash containment: one child fails, siblings still complete
* at-most-once settlement: double settle raises
* progressive disclosure via the real store
* driver_from_settings picks the mock path without an API key
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc import (  # noqa: E402
    CompletionLog,
    MockDriver,
    build_runtime,
    driver_from_settings,
)
from dhc.errors import ChannelError  # noqa: E402
from dhc.data.models import Completion  # noqa: E402

CHILD_OK = (
    "art = publish('child finding', 'child summary', 'child report body')\n"
    "result = complete('child done', artifacts=[art.id])\n"
)

CHILD_FAIL = (
    "result = fail('risk data source unavailable; requirement unreachable')\n"
)

ROOT_SCRIPT = [
    # Turn 1: publish the plan, spawn 3 children (fan-out, INFO-009).
    (
        "plan = publish('research plan', 'fan out to 3 children', "
        "{'plan': 'market research on AI agents'})\n"
        "c1 = spawn('research market size', acceptance=('done',), "
        "driver=MockDriver.single(" + repr(CHILD_OK) + "))\n"
        "c2 = spawn('research competitors', acceptance=('done',), "
        "driver=MockDriver.single(" + repr(CHILD_OK) + "))\n"
        "c3 = spawn('research risks', acceptance=('done',), "
        "driver=MockDriver.single(" + repr(CHILD_FAIL) + "))\n"
        "result = complete('spawned 3 children', artifacts=[plan.id])\n"
    ),
    # Turn 2: await every child (ensure-terminal), aggregate the artifact ids
    # of the survivors, publish the final artifact, complete.
    (
        "ids = []\n"
        "for h in (c1, c2, c3):\n"
        "    comp = await_(h)\n"
        "    if comp.status.value == 'completed':\n"
        "        ids.extend(comp.artifact_ids)\n"
        "final = publish('final report', 'aggregated findings', "
        "{'artifact_ids': ids})\n"
        "result = complete('root done', artifacts=[final.id])\n"
    ),
]


@pytest.fixture()
def runtime(tmp_path):
    """A fully-wired runtime over a fresh temp artifact root."""
    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    yield rt
    rt.stop()


def test_full_session_end_to_end(runtime):
    """Root -> publish -> fan-out -> aggregate -> settle, all real modules."""
    root = runtime.spawn(
        "Produce a market research report on AI agents",
        acceptance=(),  # empty: the driver controls settlement (multi-turn)
        driver=MockDriver(ROOT_SCRIPT),
    )
    root_completion = runtime.await_(root.id)

    # Root settles completed with the final artifact.
    assert root_completion.status.value == "completed"
    assert root_completion.summary == "root done"
    assert len(root_completion.artifact_ids) == 1

    # Three children were spawned; two completed, one failed (contained).
    children = runtime.children_of(root.id)
    assert len(children) == 3
    states = {}
    for cid in children:
        comp = runtime.await_(cid)
        states[cid] = comp.status.value
    assert sorted(states.values()) == ["completed", "completed", "failed"]

    # The root's final artifact id is present in the real store.
    final_id = root_completion.artifact_ids[0]
    assert runtime.artifact_store_real.exists(final_id)
    assert runtime.artifact_store_real.get_summary(final_id) == "aggregated findings"

    # Every child artifact id is present in the store.
    for cid in children:
        comp = runtime.await_(cid)
        for aid in comp.artifact_ids:
            assert runtime.artifact_store_real.exists(aid)

    # Boundary event log: spawned/settled/published with causal ids.
    spawned = runtime.boundary_log.read(kind="spawned")
    settled = runtime.boundary_log.read(kind="settled")
    published = runtime.boundary_log.read(kind="published")
    assert len(spawned) == 3
    assert len(settled) == 4  # 3 children + root
    assert len(published) >= 4  # plan + 2 child findings + final
    # Causal ids: every settled record links back to a spawned record.
    spawned_causal = {e["causal_id"] for e in spawned}
    for event in settled:
        if event["agent_id"] in children:
            assert event["causal_id"] in spawned_causal


def test_crash_containment_keeps_siblings_alive(runtime):
    """One child fails; siblings still complete; the root still completes."""
    root = runtime.spawn(
        "fan out with one failing child",
        acceptance=(),
        driver=MockDriver(ROOT_SCRIPT),
    )
    root_completion = runtime.await_(root.id)
    assert root_completion.status.value == "completed"

    children = runtime.children_of(root.id)
    states = {runtime.await_(cid).status.value for cid in children}
    assert "failed" in states
    assert "completed" in states
    assert len(states) == 2  # both terminal kinds present, nothing else


def test_at_most_once_settlement_raises():
    """Double settlement of the same agent raises ChannelError (INFO-046)."""
    log = CompletionLog()
    completion = Completion(agent_id="a1", status="completed", summary="done")
    log.settle(completion)
    with pytest.raises(ChannelError):
        log.settle(completion)
    assert log.get("a1") is completion


def test_progressive_disclosure_via_real_store(runtime):
    """headline -> summary -> report tiers are stored and retrievable."""
    root = runtime.spawn(
        "publish one artifact",
        acceptance=(),
        driver=MockDriver.single(
            "art = publish('headline here', 'summary here', {'body': 'full report'})\n"
            "result = complete('done', artifacts=[art.id])\n"
        ),
    )
    comp = runtime.await_(root.id)
    assert comp.status.value == "completed"
    aid = comp.artifact_ids[0]

    store = runtime.artifact_store_real
    assert store.get_headline(aid) == "headline here"
    assert store.get_summary(aid) == "summary here"
    assert store.get_report(aid) == {"body": "full report"}
    # The full artifact round-trips.
    artifact = store.get(aid)
    assert artifact.headline == "headline here"
    assert artifact.report == {"body": "full report"}


def test_driver_from_settings_picks_mock_without_key(monkeypatch):
    """Without an API key, the factory returns a MockDriver (mock path)."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    driver = driver_from_settings(mock=False)
    assert isinstance(driver, MockDriver)
    # The default script publishes and completes.
    code = driver(None)
    assert "publish(" in code
    assert "complete(" in code
    assert driver(None) is None  # script exhausted -> settle


def test_driver_from_settings_mock_flag(monkeypatch):
    """mock=True forces the mock path even with a key present."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    driver = driver_from_settings(mock=True)
    assert isinstance(driver, MockDriver)


def test_messenger_wired_on_runtime(runtime):
    """The Messenger is wired onto the same bus and reachable."""
    root = runtime.spawn(
        "send a message",
        acceptance=(),
        driver=MockDriver.single(
            "messenger.send('a1', 'hello')\n"
            "result = complete('sent')\n"
        ),
    )
    comp = runtime.await_(root.id)
    assert comp.status.value == "completed"
    # The message crossed the boundary log as a 'messaged' record.
    messaged = runtime.boundary_log.read(kind="messaged")
    assert any(e["payload"].get("body") == "hello" for e in messaged)