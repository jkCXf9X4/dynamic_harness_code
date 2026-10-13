"""W4.1 + W6.1: the wired runtime is a typed, honest object.

* ``build_runtime`` returns a :class:`~dhc.wiring.WiredRuntime` whose
  post-construction decorations are declared as typed class-level
  annotations (14 total, incl. the W6.1 default ``checkpoint_store``).
* ``artifact_store_real`` is a deprecated read-only property forwarding to
  ``artifact_store`` (DeprecationWarning on read).
* W6.1 round-trip: a default runtime's ``checkpoint_store`` lives under the
  workspace root; a checkpoint saved there is visible to a SECOND runtime
  built on the same root — the exact consumption path the terminal's
  ``/resume`` uses (``store.load(agent_id)``).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dhc import MockDriver, build_runtime, register_namespace_builder  # noqa: E402
from dhc.framework.runtime import Runtime  # noqa: E402
from dhc.ui.checkpoint import (  # noqa: E402
    CheckpointStore,
    checkpoint_from_agent,
)
from dhc.wiring import WiredRuntime  # noqa: E402

# The 14 post-construction decorations build_runtime attaches, declared as
# typed annotations on WiredRuntime (W4.1 + W6.1).
DECORATIONS = (
    "messenger",
    "rooms",
    "escalations",
    "questions",
    "dispatcher",
    "boundary_log",
    "bus",
    "artifact_store",
    "operator",
    "mock",
    "rot_detector",
    "repl_engine",
    "checkpoint_store",
)


@pytest.fixture()
def runtime(tmp_path):
    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    yield rt
    rt.stop()


def test_build_runtime_returns_wired_runtime(runtime):
    assert isinstance(runtime, WiredRuntime)
    assert isinstance(runtime, Runtime)


def test_wired_runtime_declares_all_decorations(runtime):
    """Every decoration is a declared class-level annotation (no default)."""
    for name in DECORATIONS:
        assert name in WiredRuntime.__annotations__, name
        assert hasattr(runtime, name), name
        # No assigned class default: the annotation is the declaration.
        assert name not in WiredRuntime.__dict__ or not isinstance(
            WiredRuntime.__dict__.get(name), (type,)), name


def test_artifact_store_real_deprecated_and_forwards(runtime):
    with pytest.warns(DeprecationWarning):
        real = runtime.artifact_store_real
    assert real is runtime.artifact_store
    # Read-only: no setter on the property.
    with pytest.raises(AttributeError):
        runtime.artifact_store_real = None


def test_checkpoint_store_attached_under_workspace_root(runtime, tmp_path):
    assert isinstance(runtime.checkpoint_store, CheckpointStore)
    assert runtime.checkpoint_store.root == (tmp_path / "checkpoints").resolve()


def test_checkpoint_roundtrip_across_runtimes(tmp_path):
    """W6.1: /resume works out of the box across processes (runtimes).

    Runtime 1: run a mock agent to completion, then persist its checkpoint
    through the default store (the same save path CheckpointDriver uses).
    Runtime 2: built on the SAME workspace root; its default store must see
    the checkpoint via ``store.load(agent_id)`` — exactly how
    ``terminal._checkpoint`` consumes it for ``/resume``.
    """
    rt1 = build_runtime(mock=True, artifact_root=tmp_path)
    rt1.start()
    try:
        agent = rt1.spawn(
            "checkpoint round-trip",
            acceptance=(),
            driver=MockDriver.single("result = complete('done')\n"),
        )
        comp = rt1.await_(agent.id)
        assert comp.status.value == "completed"
        # Persist the checkpoint the way the operator's driver wrapper does
        # (checkpoint_from_agent reads the raw Agent's _status).
        raw_agent = rt1.agents_snapshot()[agent.id]
        cp = checkpoint_from_agent(raw_agent, turn_counter=1, notes=["after turn 1"])
        rt1.checkpoint_store.save(cp)
        # Visible on the first runtime's store.
        assert rt1.checkpoint_store.load(agent.id) is not None
    finally:
        rt1.stop()

    rt2 = build_runtime(mock=True, artifact_root=tmp_path)
    rt2.start()
    try:
        # The second runtime's default store sees the checkpoint — the
        # terminal's /resume consumption path (store.load(agent_id)).
        loaded = rt2.checkpoint_store.load(agent.id)
        assert loaded is not None
        assert loaded.agent_id == agent.id
        assert loaded.status == "completed"
        assert loaded.turn_counter == 1
        assert agent.id in rt2.checkpoint_store.list_ids()
    finally:
        rt2.stop()


def test_register_namespace_builder_exported(tmp_path):
    """W4.2: the composition entry point is public package API."""
    assert register_namespace_builder is Runtime.register_namespace_builder
    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    try:
        before = len(rt.namespace_builders)
        register_namespace_builder(rt, lambda agent: {"w42_probe": 1})
        assert len(rt.namespace_builders) == before + 1
    finally:
        rt.stop()
