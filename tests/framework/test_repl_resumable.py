"""Tests for the IMP-001 Step 1 resumable-run primitives on ReplEngine.

Covers install/advance (yield-window stepping, StopIteration finish),
per-advance snapshot + abandon-on-timeout (INFO-020 semantics, now per-step),
inject (namespace refresh between steps), suspend/resume (park/continue),
kill (abandon + clear), and run_block (non-locking nested exec — no deadlock
when called from inside an advance). The existing tests/test_repl.py suite
covers the unchanged execute/reset/globals_for/has_workspace contract.
"""

import threading
import time

import pytest

from dhc.data.models import Result
from dhc.framework.repl import AdvanceOutcome, ReplEngine

pytestmark = pytest.mark.slow


def read(engine, agent_id, expr):
    """Run a turn that returns *expr*'s value through the result slot."""
    return engine.execute(
        agent_id,
        f"result = Result(done=True, ok=True, value={expr})",
        namespace={"Result": Result},
    )


# -- install / advance ----------------------------------------------------- #


def test_install_advance_yields_values_in_order():
    engine = ReplEngine()

    def runner():
        yield "first"
        yield "second"
        yield "third"

    engine.install("a1", runner())
    o1 = engine.advance("a1")
    assert o1.kind == "yield" and o1.value == "first"
    o2 = engine.advance("a1")
    assert o2.kind == "yield" and o2.value == "second"
    o3 = engine.advance("a1")
    assert o3.kind == "yield" and o3.value == "third"
    # StopIteration ends the runner.
    o4 = engine.advance("a1")
    assert o4.kind == "finished"
    # The runner is gone: a further advance reports not_installed.
    o5 = engine.advance("a1")
    assert o5.kind == "not_installed"


def test_advance_without_install():
    engine = ReplEngine()
    assert engine.advance("a1").kind == "not_installed"


def test_workspace_mutations_persist_across_advances():
    """A yield is a checkpoint: mutations from one step are visible in the
    next (the workspace is the persistent state between steps)."""
    engine = ReplEngine()
    engine.execute("a1", "counter = 0")

    def runner():
        engine.run_block("a1", "counter = counter + 1")
        yield "one"
        engine.run_block("a1", "counter = counter + 1")
        yield "two"

    engine.install("a1", runner())
    assert engine.advance("a1").value == "one"
    assert engine.advance("a1").value == "two"
    check = read(engine, "a1", "counter")
    assert check.ok is True
    assert check.value == 2


def test_advance_error_contained():
    engine = ReplEngine()

    def runner():
        yield "one"
        raise ValueError("boom")

    engine.install("a1", runner())
    assert engine.advance("a1").value == "one"
    outcome = engine.advance("a1")
    assert outcome.kind == "error"
    assert outcome.reason == "ValueError: boom"
    # A generator that raised is finished and is never resumed.
    assert engine.advance("a1").kind == "not_installed"


# -- timeout containment: rollback + abandon ------------------------------- #


def test_advance_timeout_rolls_back_and_abandons():
    engine = ReplEngine()
    engine.execute("a1", "x = 1")

    def runner():
        engine.run_block("a1", "x = 99")  # partial mutation before the hang
        while True:
            pass
        yield  # unreachable

    engine.install("a1", runner())
    start = time.monotonic()
    outcome = engine.advance("a1", timeout=0.1)
    elapsed = time.monotonic() - start
    assert outcome.kind == "timeout"
    assert elapsed < 0.9, f"advance blocked for {elapsed:.2f}s"
    # The timed-out step's partial mutation must be rolled back (INFO-020,
    # now per-step).
    check = read(engine, "a1", "x")
    assert check.ok is True
    assert check.value == 1
    # The generator is abandoned: a subsequent advance never resumes it.
    outcome2 = engine.advance("a1")
    assert outcome2.kind == "abandoned"


def test_advance_timeout_workspace_usable_afterwards():
    engine = ReplEngine()
    engine.execute("a1", "x = 1")

    def runner():
        while True:
            pass
        yield  # unreachable

    engine.install("a1", runner())
    outcome = engine.advance("a1", timeout=0.1)
    assert outcome.kind == "timeout"
    # The workspace stays usable after a timeout (INFO-020).
    check = read(engine, "a1", "x")
    assert check.ok is True
    assert check.value == 1


def test_advance_timeout_rolls_back_nested_mutation():
    """The per-advance snapshot copies nested plain containers: an in-place
    mutation of a nested dict/list by the timed-out step rolls back."""
    engine = ReplEngine()
    engine.execute("a1", "d = {'inner': {'n': 1}, 'items': [1, 2]}")

    def runner():
        engine.run_block("a1", "d['inner']['n'] = 99\nd['items'].append(3)")
        time.sleep(10)  # sleeps (releases the GIL) until the timeout fires
        yield  # unreachable

    engine.install("a1", runner())
    outcome = engine.advance("a1", timeout=0.1)
    assert outcome.kind == "timeout"
    check = read(engine, "a1", "d")
    assert check.ok is True
    assert check.value == {"inner": {"n": 1}, "items": [1, 2]}


# -- cancellation boundaries ----------------------------------------------- #


def test_run_block_cancelled_stops_before_the_block():
    """A cancelled turn raises at the block boundary instead of running."""
    from dhc.framework.repl import TurnCancelled

    engine = ReplEngine()
    engine.execute("a1", "x = 1")
    engine.request_cancel("a1")
    with pytest.raises(TurnCancelled):
        engine.run_block("a1", "x = 99")
    assert read(engine, "a1", "x").value == 1


def test_advance_cancelled_by_predicate_abandons_runner():
    """The engine's bound cancel predicate ends a running step promptly."""
    engine = ReplEngine()
    engine.execute("a1", "x = 1")
    flag = threading.Event()
    engine.bind_cancel("a1", flag.is_set)

    def runner():
        time.sleep(10)  # sleeps (releases the GIL) until the cancel lands
        yield  # unreachable

    engine.install("a1", runner())
    timer = threading.Timer(0.1, flag.set)
    timer.start()
    start = time.monotonic()
    outcome = engine.advance("a1", timeout=10)
    elapsed = time.monotonic() - start
    assert outcome.kind == "cancelled"
    assert elapsed < 2, f"cancelled advance blocked for {elapsed:.2f}s"
    assert engine.advance("a1").kind == "abandoned"


# -- inject ---------------------------------------------------------------- #


def test_inject_adds_and_updates_workspace_names():
    engine = ReplEngine()
    engine.execute("a1", "x = 1")
    engine.inject("a1", {"x": 2, "y": 3})
    assert read(engine, "a1", "x").value == 2
    assert read(engine, "a1", "y").value == 3


def test_inject_refreshes_namespace_between_steps():
    """The pump refreshes the in-code surface between steps; the generator
    sees the new values on its next advance."""
    engine = ReplEngine()
    seen = []
    engine.inject("a1", {"injected": "first", "seen": seen})

    def runner():
        engine.run_block("a1", "seen.append(injected)")
        yield "step1"
        engine.run_block("a1", "seen.append(injected)")
        yield "step2"

    engine.install("a1", runner())
    engine.advance("a1")
    engine.inject("a1", {"injected": "second"})
    engine.advance("a1")
    assert seen == ["first", "second"]


# -- suspend / resume / kill ---------------------------------------------- #


def test_suspend_resume_parks_and_continues():
    engine = ReplEngine()

    def runner():
        yield "one"
        yield "two"
        yield "three"

    engine.install("a1", runner())
    assert engine.advance("a1").value == "one"
    engine.suspend("a1")
    # While parked, advance does not run the generator.
    outcome = engine.advance("a1")
    assert outcome.kind == "suspended"
    engine.resume("a1")
    # Resume continues from the same point.
    assert engine.advance("a1").value == "two"
    assert engine.advance("a1").value == "three"
    assert engine.advance("a1").kind == "finished"


def test_kill_abandons_and_clears_runner():
    engine = ReplEngine()

    def runner():
        yield "one"
        yield "two"

    engine.install("a1", runner())
    assert engine.advance("a1").value == "one"
    engine.kill("a1")
    outcome = engine.advance("a1")
    assert outcome.kind == "abandoned"
    # kill clears the installed runner; a fresh install works.
    engine.install("a1", runner())
    assert engine.advance("a1").value == "one"


# -- run_block (non-locking nested exec) ----------------------------------- #


def test_run_block_standalone():
    engine = ReplEngine()
    engine.execute("a1", "x = 1")
    result = engine.run_block("a1", "x = x + 1")
    assert result.ok is True
    assert read(engine, "a1", "x").value == 2


def test_run_block_nested_inside_advance_no_deadlock():
    """The generator's code calls a workspace function that itself invokes
    run_block. run_block bypasses the per-agent lock, so the nested exec from
    inside an advance (which holds the lock) does not deadlock. A deadlock
    would surface as a timeout outcome and fail the assertions below."""
    engine = ReplEngine()
    # A workspace function that invokes run_block (the nested exec).
    engine.execute(
        "a1",
        "def step():\n"
        "    run_block('a1', 'nested_value = 42')\n"
        "    return 'nested-ran'",
        namespace={"run_block": engine.run_block},
    )

    def runner():
        # Generator code: run a block that calls the workspace function.
        engine.run_block("a1", "step_result = step()")
        yield "done"

    engine.install("a1", runner())
    outcome = engine.advance("a1", timeout=5)
    assert outcome.kind == "yield"
    assert outcome.value == "done"
    check = read(engine, "a1", "step_result")
    assert check.ok is True
    assert check.value == "nested-ran"
    assert read(engine, "a1", "nested_value").value == 42


# -- coexistence with the unchanged execute path --------------------------- #


def test_execute_coexists_with_installed_runner():
    engine = ReplEngine()

    def runner():
        yield "one"

    engine.install("a1", runner())
    result = engine.execute("a1", "x = 1")
    assert result.ok is True
    assert engine.advance("a1").value == "one"