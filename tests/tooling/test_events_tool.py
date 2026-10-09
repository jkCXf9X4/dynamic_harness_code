"""G-04: settled-event access as a workspace tool + agent-chosen consumption.

Closes vision gap A7 (INFO-053): "event consumption — which settled events
the agent reads, and when — is under agent control." Today the agent reaches
its settled-event stream only through the default runner's ``observe`` call
(or by rewriting the runner). This adds an ``events`` workspace tool (the
12th tool, registered like the other 11) that gives the agent its own
settled events with a consume-once cursor, so the agent can consume events
on its own schedule without rewriting the runner.

The tool wraps the runtime's existing event stream (``Runtime.tool_events``
over the same non-destructive ``events:<id>`` peek fan-out seam) — it does
NOT build a second event path. The discipline guarantees (FIFO, at-most-once,
persist-before-execute) remain runtime-owned; the tool only advances a
read cursor over the already-persisted, ordered stream.

The tool keeps its OWN consume-once cursor (``_tool_event_cursors``),
separate from the default runner's ``observe`` (``_event_cursors``) and the
caps watchdog (``_caps_cursors``), so the agent's consumption never steals
from the default loop's digest — matching the codebase's established
multi-consumer pattern (the drain-race fix).
"""

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc.data.models import AgentStatus, EventKind  # noqa: E402
from dhc.framework.runtime import Runtime  # noqa: E402
from dhc.tooling.framework_tools import register_default_tools  # noqa: E402
from dhc.llm.driver import MockDriver  # noqa: E402


# --------------------------------------------------------------------------- #
# Unit tests: the tool's consume-once cursor (bare Runtime, no pump)
# --------------------------------------------------------------------------- #


def test_events_tool_consume_once():
    """The ``events`` tool gives the agent its own settled events with a
    consume-once cursor: a second call returns only events published since
    the first."""
    runtime = Runtime()
    register_default_tools(runtime)
    from dhc.framework.agent import Agent

    agent = Agent(id="a1", requirement="r")
    ns = runtime._build_namespace(agent)
    assert "events" in ns, "the events tool is not installed"

    # Publish 3 settled events to a1's stream.
    for i in range(3):
        runtime._emit("a1", EventKind.turn_started, payload={"step": i})

    first = ns["events"]()
    assert len(first) == 3, "first read should return all 3 settled events"
    # Consume-once: a second read returns nothing new.
    second = ns["events"]()
    assert second == [], "second read should be empty (consume-once)"
    # A new event is picked up on the next read.
    runtime._emit("a1", EventKind.turn_completed, payload={})
    third = ns["events"]()
    assert len(third) == 1, "third read should return only the new event"
    assert third[0].kind == EventKind.turn_completed


def test_events_tool_cursor_independent_of_observe():
    """The tool's cursor is independent of the default runner's ``observe``
    cursor (``Runtime.events``): the agent's consumption never steals from
    the default loop's digest, and vice versa."""
    runtime = Runtime()
    for i in range(3):
        runtime._emit("a1", EventKind.turn_started, payload={"step": i})

    # The default runner's observe cursor (Runtime.events).
    observed = runtime.events("a1")
    assert len(observed) == 3
    # The tool's own cursor: still sees all 3 (not stolen by the observe).
    tool_read = runtime.tool_events("a1")
    assert len(tool_read) == 3, "the tool must not steal from the observe"
    # Each cursor advanced independently.
    assert runtime.events("a1") == [], "observe cursor advanced"
    assert runtime.tool_events("a1") == [], "tool cursor advanced"


def test_events_tool_fifo_order():
    """The tool returns events in FIFO (publish) order."""
    runtime = Runtime()
    runtime._emit("a1", EventKind.turn_started, payload={"step": 1})
    runtime._emit("a1", EventKind.turn_completed, payload={"step": 1})
    runtime._emit("a1", EventKind.turn_started, payload={"step": 2})
    events = runtime.tool_events("a1")
    assert [e.kind for e in events] == [
        EventKind.turn_started,
        EventKind.turn_completed,
        EventKind.turn_started,
    ]
    assert [e.payload.get("step") for e in events] == [1, 1, 2]


# --------------------------------------------------------------------------- #
# Integration: an agent that reads events on its own schedule (non-default
# consumption pattern) and completes normally.
# --------------------------------------------------------------------------- #


def _pumped_runtime(tmp_path, **settings_kwargs):
    """A fully-wired runtime (ReplEngine + fabrication kit) over tmp_path.

    Replicated from tests/test_imp001_acceptance.py so this fixture is
    self-contained (no cross-test-module imports).
    """
    from dhc.data.config import Settings
    from dhc.wiring import build_runtime

    settings = Settings(
        workspace_root=tmp_path,
        artifact_root=tmp_path,
        **settings_kwargs,
    )
    rt = build_runtime(mock=True, artifact_root=tmp_path, settings=settings)
    rt.start()
    return rt


def test_agent_reads_events_on_own_schedule(tmp_path):
    """A non-default consumption pattern: the agent replaces its ``__runner``
    with one that reads its settled events via the ``events`` tool TWICE per
    turn (the default runner reads once per turn via ``observe``), on its own
    schedule, and completes normally.

    This proves the agent can consume events on its own schedule without
    rewriting the runner's consumption to a second event path — the tool is
    the first-class surface, and the consume-once cursor holds (the second
    read in a turn returns nothing new).
    """
    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn(
            "g04",
            driver=MockDriver(
                [
                    "__runner = '''\n"
                    "def __runner__(ctx):\n"
                    "    ctx['state']['reads'] = []\n"
                    "    for turn in range(2):\n"
                    "        # Read the settled events TWICE per turn (a\n"
                    "        # non-default schedule: the default runner\n"
                    "        # reads once per turn via observe()).\n"
                    "        first = events()\n"
                    "        second = events()\n"
                    "        ctx['state']['reads'].append([len(first), len(second)])\n"
                    "        yield 'step'\n"
                    "    complete('done reading events on my own schedule')\n"
                    "'''\n"
                ]
            ),
        )
        completion = handle.await_()
        # The agent completed normally (not failed/cancelled/timeout).
        assert completion.status == AgentStatus.completed
        assert completion.summary == "done reading events on my own schedule"
        assert rt.result(handle.id).ok

        ws = rt.repl_engine.globals_for(handle.id)
        reads = ws["state"]["reads"]
        # Two turns, each reading events twice (the agent's own schedule).
        assert len(reads) == 2, f"expected 2 turns of reads, got {reads}"
        for turn, (first, second) in enumerate(reads):
            # The first read in each turn saw settled events (non-empty).
            assert first >= 1, f"turn {turn}: first read should be non-empty"
            # Consume-once: the second read (no new events published between
            # the two reads within the turn) returns nothing.
            assert second == 0, (
                f"turn {turn}: second read should be empty (consume-once), "
                f"got {second}"
            )
    finally:
        rt.stop()
