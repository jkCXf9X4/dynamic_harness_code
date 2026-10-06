"""Tests for dhc.repl — the per-agent persistent REPL engine.

Covers the INFO-050 workspace semantics (persistence, isolation,
serialization, namespace injection), the turn result convention, crash
containment (INFO-005: a failed turn preserves state) and timeout containment
(INFO-020: no hang, workspace usable and uncorrupted afterwards).

Per the turn result convention, a block returns a value only by assigning
``result = Result(...)``; a block that does not yields
``Result(done=True, ok=True, value=None)``.
"""

import threading
import time

from dhc.models import Result
from dhc.repl import ReplEngine


def read(engine, agent_id, expr):
    """Run a turn that returns *expr*'s value through the result slot."""
    return engine.execute(
        agent_id,
        f"result = Result(done=True, ok=True, value={expr})",
        namespace={"Result": Result},
    )


def test_state_persists_across_turns():
    engine = ReplEngine()
    engine.execute("a1", "x = 1")
    result = read(engine, "a1", "x")
    assert result.done is True
    assert result.ok is True
    assert result.value == 1


def test_namespace_injection_visible_in_turn():
    engine = ReplEngine()
    result = engine.execute(
        "a1",
        "result = Result(done=True, ok=True, value=agent_name)",
        namespace={"agent_name": "root", "Result": Result},
    )
    assert result.ok is True
    assert result.value == "root"


def test_namespace_injection_caller_wins_over_stale_workspace():
    engine = ReplEngine()
    engine.execute("a1", "agent_name = 'stale'")
    result = engine.execute(
        "a1",
        "result = Result(done=True, ok=True, value=agent_name)",
        namespace={"agent_name": "fresh", "Result": Result},
    )
    assert result.ok is True
    assert result.value == "fresh"


def test_namespace_values_persist_in_workspace():
    engine = ReplEngine()
    engine.execute("a1", "seen = agent_name", namespace={"agent_name": "root"})
    result = read(engine, "a1", "seen")
    assert result.ok is True
    assert result.value == "root"


def test_result_variable_convention_returned():
    engine = ReplEngine()
    result = engine.execute(
        "a1",
        "result = Result(done=True, ok=True, value='hello')",
        namespace={"Result": Result},
    )
    assert result is not None
    assert result.done is True
    assert result.ok is True
    assert result.value == "hello"


def test_default_result_when_no_result_variable():
    engine = ReplEngine()
    result = engine.execute("a1", "y = 2")
    assert result.done is True
    assert result.ok is True
    assert result.value is None


def test_stale_result_variable_not_returned():
    engine = ReplEngine()
    engine.execute(
        "a1", "result = Result(done=True, ok=True, value='old')",
        namespace={"Result": Result},
    )
    result = engine.execute("a1", "z = 3")
    assert result.done is True
    assert result.ok is True
    assert result.value is None


def test_exception_returns_failed_result_with_reason():
    engine = ReplEngine()
    result = engine.execute("a1", "raise ValueError('boom')")
    assert result.done is True
    assert result.ok is False
    assert result.reason == "ValueError: boom"


def test_exception_preserves_workspace():
    engine = ReplEngine()
    engine.execute("a1", "x = 1")
    result = engine.execute("a1", "x = 2\nraise RuntimeError('kaboom')")
    assert result.done is True
    assert result.ok is False
    assert result.reason == "RuntimeError: kaboom"
    # The failed turn must not destroy the agent's state (INFO-005).
    check = read(engine, "a1", "x")
    assert check.ok is True
    assert check.value == 2


def test_timeout_returns_failed_result_without_hang():
    engine = ReplEngine()
    start = time.monotonic()
    result = engine.execute("a1", "import time\ntime.sleep(1)", timeout=0.1)
    elapsed = time.monotonic() - start
    assert result.done is True
    assert result.ok is False
    assert result.reason == "turn timed out"
    assert elapsed < 0.9, f"execute blocked for {elapsed:.2f}s"


def test_timeout_workspace_usable_afterwards():
    engine = ReplEngine()
    engine.execute("a1", "x = 1")
    result = engine.execute("a1", "import time\ntime.sleep(1)", timeout=0.1)
    assert result.reason == "turn timed out"
    # Workspace must remain usable after a timeout (INFO-020).
    check = read(engine, "a1", "x")
    assert check.ok is True
    assert check.value == 1


def test_timeout_rolls_back_partial_mutations():
    engine = ReplEngine()
    engine.execute("a1", "x = 1")
    result = engine.execute(
        "a1", "x = 99\nimport time\ntime.sleep(1)", timeout=0.1
    )
    assert result.reason == "turn timed out"
    # The timed-out turn's partial mutation must not corrupt the workspace.
    check = read(engine, "a1", "x")
    assert check.ok is True
    assert check.value == 1


def test_per_agent_isolation():
    engine = ReplEngine()
    engine.execute("a1", "x = 1")
    engine.execute("a2", "x = 2")
    assert read(engine, "a1", "x").value == 1
    assert read(engine, "a2", "x").value == 2
    # A name defined in one agent is invisible in the other.
    engine.execute("a1", "secret = 's1'")
    result = read(engine, "a2", "secret")
    assert result.ok is False
    assert result.reason.startswith("NameError")


def test_no_concurrent_execution_per_agent():
    engine = ReplEngine()
    order: list[str] = []
    started = threading.Event()

    def first() -> None:
        engine.execute(
            "a1",
            "import time\n"
            "order.append('first-start')\n"
            "started.set()\n"
            "time.sleep(0.2)\n"
            "order.append('first-end')",
            namespace={"order": order, "started": started},
        )

    def second() -> None:
        engine.execute("a1", "order.append('second')", namespace={"order": order})

    t1 = threading.Thread(target=first, daemon=True)
    t2 = threading.Thread(target=second, daemon=True)
    t1.start()
    assert started.wait(5), "first turn never started"
    t2.start()  # blocks on the per-agent lock while the first turn runs
    t1.join(5)
    t2.join(5)
    assert not t1.is_alive() and not t2.is_alive()
    # The second turn must have run strictly after the first finished.
    assert order == ["first-start", "first-end", "second"]


def test_reset_drops_workspace():
    engine = ReplEngine()
    engine.execute("a1", "x = 1")
    assert engine.has_workspace("a1") is True
    engine.reset("a1")
    assert engine.has_workspace("a1") is False
    assert engine.globals_for("a1") == {}
    result = read(engine, "a1", "x")
    assert result.ok is False
    assert result.reason.startswith("NameError")


def test_globals_for_returns_copy():
    engine = ReplEngine()
    engine.execute("a1", "x = 1")
    view = engine.globals_for("a1")
    assert view["x"] == 1
    view["x"] = 999  # mutating the view must not touch the workspace
    assert read(engine, "a1", "x").value == 1


def test_has_workspace_false_before_first_turn():
    engine = ReplEngine()
    assert engine.has_workspace("a1") is False
    engine.execute("a1", "x = 1")
    assert engine.has_workspace("a1") is True