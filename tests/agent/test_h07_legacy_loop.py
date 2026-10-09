"""H-07 (decision 0013): the legacy loop path is required — pinned, not retired.

The pump is the main path for every wired runtime (``build_runtime``), but
the bare in-memory core — ``Runtime()`` with its default ``_MemoryEngine``
— has none of the pump's resumable-runner primitives. The legacy turn loop
is that core's loop, and the production ``dhc`` CLI (``src/dhc/cli.py``)
runs on it. These tests pin the requirement so the dispatch or the path
cannot silently change.
"""

from __future__ import annotations

from dhc.agent.runtime import Runtime
from dhc.data.models import AgentStatus, EventKind

# The pump's engine contract (IMP-001 Step 1): the resumable-runner
# primitives pump_loop drives an agent through.
PUMP_PRIMITIVES = (
    "install",
    "advance",
    "inject",
    "kill",
    "suspend",
    "resume",
    "globals_for",
    "has_workspace",
)


def test_h07_bare_runtime_falls_back_to_legacy():
    """A bare ``Runtime()`` (the CLI's shape, cli.py:130) is not pumpable.

    The default engine is ``_MemoryEngine`` (turn-based ``exec``) and no
    ``repl_engine`` is set — the dispatch condition routes it to the
    legacy turn loop.
    """
    rt = Runtime()
    try:
        # No repl_engine attribute exists on the bare core (supports_pump
        # reads it with getattr(..., None)).
        assert getattr(rt, "repl_engine", None) is None
        assert not hasattr(rt.engine, "advance")
        assert rt._supports_pump() is False
    finally:
        rt.stop()


def test_h07_wired_runtime_uses_pump():
    """The wired runtime (``build_runtime``) is pumpable: the main path.

    The dispatch never sends a wired agent to the legacy loop.
    """
    from dhc.wiring import build_runtime

    rt = build_runtime(mock=True)
    try:
        assert rt._supports_pump() is True
    finally:
        rt.stop()


def test_h07_legacy_path_drives_bare_runtime_agents(tmp_path):
    """The legacy path is live: a bare-Runtime agent settles through it.

    An agent spawned on a bare ``Runtime()`` completes, and its event
    stream carries the legacy turn loop's ``turn_started`` payload shape
    (``{"code": ...}``) rather than the pump's (``{"step": ...}``) — the
    path is exercised end-to-end, not dead code.
    """
    from dhc.llm.driver import MockDriver

    rt = Runtime()
    try:
        handle = rt.spawn("legacy", driver=MockDriver.single("complete('ok')"))
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "ok"
        started = [e for e in rt.events(handle.id) if e.kind == EventKind.turn_started]
        assert started, "the legacy loop emitted turn_started events"
        assert all("code" in e.payload for e in started)
        assert not any("step" in e.payload for e in started)
    finally:
        rt.stop()


def test_h07_memory_engine_lacks_pump_primitives():
    """The mechanical reason the legacy path must stay: ``_MemoryEngine``
    provides none of the eight primitives the pump drives an agent
    through."""
    from dhc.agent.runtime import _MemoryEngine

    engine = _MemoryEngine()
    missing = [name for name in PUMP_PRIMITIVES if not hasattr(engine, name)]
    assert missing == list(PUMP_PRIMITIVES), (
        "if _MemoryEngine grows pump primitives, decision 0013 should be "
        f"revisited (now missing: {missing})"
    )


def test_h07_repl_engine_provides_pump_primitives():
    """The contrast: ``ReplEngine`` provides all eight, so the pump's
    engine contract is real, not vacuous."""
    from dhc.agent.repl import ReplEngine

    engine = ReplEngine()
    missing = [name for name in PUMP_PRIMITIVES if not hasattr(engine, name)]
    assert missing == [], f"ReplEngine lost pump primitives: {missing}"
