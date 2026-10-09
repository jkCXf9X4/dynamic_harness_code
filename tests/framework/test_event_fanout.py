"""Tests for the event-bus fan-out seam (the ``_MemoryBus`` drain-race fix).

The four consumers of the ``events:<agent_id>`` topics — the ceiling-caps
watchdog, ``Runtime.events`` (the driver's recent context reads the same
surface), and the StateWriter poll thread — historically raced on a
DESTRUCTIVE ``drain``: the first drainer starved the rest. The fix adds a
non-destructive ``peek`` and gives every consumer its own cursor, so each
consumer observes every event.

These tests prove the fan-out: each consumer pattern receives every event,
the per-step delta semantics of the message-rate cap are preserved, the
StateWriter poll thread forwards each event exactly once (no 50 ms
re-forward), and concurrent consumers lose no events. The ``completions:``
topics stay destructive (INFO-046 at-most-once) — that contract is asserted
too.
"""

import json
import threading
import time
from pathlib import Path

from dhc.framework.runtime import Runtime, _MemoryBus
from dhc.ui.state import StateWriter
from dhc.data.models import Event, EventKind
from dhc.llm.driver import LLMDriver


# --------------------------------------------------------------------------- #
# Helpers (duplicated per house style — no conftest.py in this tree)
# --------------------------------------------------------------------------- #


class ScriptedDriver:
    """A driver that replays a fixed script of code blocks, then settles."""

    def __init__(self, *blocks: str) -> None:
        self.blocks = list(blocks)
        self.calls = 0

    def __call__(self, agent):
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


def _settings(tmp_path, max_messages_per_step):
    """A Settings object forcing the message-rate cap (tiny settings object)."""
    from dhc.data.config import HarnessConfig, SafetyConfig, Settings

    return Settings(
        workspace_root=Path(tmp_path),
        artifact_root=Path(tmp_path),
        config=HarnessConfig(
            safety=SafetyConfig(max_messages_per_step=max_messages_per_step)
        ),
    )


def _marker(agent_id: str, i: int) -> Event:
    """A distinctive event so assertions can pick it out of the history."""
    return Event(
        kind=EventKind.message_sent,
        agent_id=agent_id,
        payload={"marker": i},
    )


# --------------------------------------------------------------------------- #
# The bus seam: peek is non-destructive, drain keeps its contract
# --------------------------------------------------------------------------- #


def test_peek_does_not_consume():
    bus = _MemoryBus()
    bus.publish("events:a1", "e1")
    bus.publish("events:a1", "e2")
    bus.publish("events:a1", "e3")

    first = bus.peek("events:a1")
    second = bus.peek("events:a1")
    assert first == ["e1", "e2", "e3"]
    assert second == ["e1", "e2", "e3"]  # nothing consumed by either peek


def test_drain_contract_unchanged_completions_stay_at_most_once():
    """``drain`` stays destructive — the ``completions:`` contract (INFO-046)."""
    bus = _MemoryBus()
    bus.publish("completions:a1", "c1")
    bus.publish("completions:a1", "c2")

    assert bus.drain("completions:a1") == ["c1", "c2"]
    assert bus.drain("completions:a1") == []  # consumed exactly once
    assert bus.peek("completions:a1") == []


def test_memory_bus_peek_publish_drain_thread_safe():
    """Concurrent publishers/readers never corrupt the topic (bus unit)."""
    bus = _MemoryBus()
    errors: list = []

    def worker() -> None:
        try:
            for i in range(250):
                bus.publish("events:x", i)
                seen = bus.peek("events:x")
                assert isinstance(seen, list)
        except Exception as exc:  # noqa: BLE001 - recorded and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)

    assert not errors
    drained = bus.drain("events:x")
    assert len(drained) == 4 * 250  # nothing lost, nothing duplicated


# --------------------------------------------------------------------------- #
# Consumer 1 — the caps watchdog: per-step delta, no steal
# --------------------------------------------------------------------------- #


def test_watchdog_counts_per_step_delta_without_consuming(tmp_path):
    """The message-rate cap counts the per-step DELTA, not the cumulative peek.

    A raw cumulative peek would change gate-(f) behavior: the same backlog
    would trip the cap on every later step. The watchdog must also not
    consume the events it counts (the historical drain stole them from the
    other consumers).
    """
    rt = make_runtime(settings=_settings(tmp_path, max_messages_per_step=3))
    try:
        handle = rt.spawn("do it", driver=ScriptedDriver("complete('done')"))
        handle.await_()
        agent_id = handle.id
        topic = f"events:{agent_id}"

        # First check: the watermark starts at zero, so this call absorbs the
        # agent's own history (turn_started / child_settled / ...) and must
        # not trip a cap of 3 on a settled single-turn agent... it may exceed
        # 3 if the history is longer, so only assert it does not consume.
        rt._caps_watchdog(agent_id, rt.engine, 1, time.monotonic())
        before = len(rt.event_bus.peek(topic))
        assert before > 0  # the history is intact after the watchdog ran

        # Step 2: exactly 3 fresh events -> delta 3, cap 3 -> not exceeded.
        for i in range(3):
            rt.event_bus.publish(topic, _marker(agent_id, i))
        cap = rt._caps_watchdog(agent_id, rt.engine, 2, time.monotonic())
        assert cap is None
        assert len(rt.event_bus.peek(topic)) == before + 3  # still intact

        # Step 3: one more event (4 markers total). A cumulative count would
        # be 4 > 3 and trip; the per-step delta is 1 -> not exceeded.
        rt.event_bus.publish(topic, _marker(agent_id, 3))
        cap = rt._caps_watchdog(agent_id, rt.engine, 3, time.monotonic())
        assert cap is None

        # The cap still fires on a genuinely oversized step (gate (f)).
        for i in range(4, 8):
            rt.event_bus.publish(topic, _marker(agent_id, i))
        cap = rt._caps_watchdog(agent_id, rt.engine, 4, time.monotonic())
        assert cap == "messages_per_step"
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# Consumers 2 + 3 — Runtime.events and the driver's recent context
# --------------------------------------------------------------------------- #


def test_events_and_recent_context_receive_every_event(tmp_path):
    """After the watchdog ran, ``Runtime.events`` still returns every event,
    and the driver's recent context (the same surface) receives the events
    published after it."""
    rt = make_runtime()
    try:
        handle = rt.spawn("do it", driver=ScriptedDriver("complete('done')"))
        handle.await_()
        agent = rt.get(handle.id)
        agent_id = handle.id
        topic = f"events:{agent_id}"

        # The watchdog ran first (consumer 1) — historically its drain stole
        # the topic, so this would have returned [].
        rt._caps_watchdog(agent_id, rt.engine, 1, time.monotonic())
        events = rt.events(agent_id)
        kinds = [e.kind for e in events]
        assert EventKind.turn_started in kinds
        assert EventKind.child_settled in kinds

        # Consume-once per caller is preserved (the historical semantics of
        # the public API): a second read returns only events published since.
        assert rt.events(agent_id) == []

        # Consumer 3 — the driver's recent context reads via runtime.events:
        # events published now are received (formatted), not stolen by the
        # watchdog's earlier read.
        rt.event_bus.publish(topic, _marker(agent_id, 0))
        context = LLMDriver._recent_context(agent)
        assert "message_sent" in context
        assert "marker" in context
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# Consumer 4 — the StateWriter poll thread: its own cursor, no re-forward
# --------------------------------------------------------------------------- #


def test_statewriter_poll_forwards_each_event_exactly_once(tmp_path):
    """The poll thread keeps its own watermark over the non-destructive
    stream: every event is forwarded exactly once, and old events are NOT
    re-forwarded on every 50 ms poll."""
    rt = make_runtime()
    handle = rt.spawn("root task", driver=ScriptedDriver("complete('done')"))
    assert wait_for(lambda: rt.is_settled(handle.id))

    writer = StateWriter(rt, root=tmp_path, snapshot_interval=60.0)
    writer.attach()  # in-memory bus: starts the poll thread

    # Two marker events after attach: the poll thread must forward each
    # exactly once (its cursor starts at zero, so the agent's own history is
    # forwarded too — the markers are what we count).
    topic = f"events:{handle.id}"
    rt.event_bus.publish(topic, _marker(handle.id, 0))
    rt.event_bus.publish(topic, _marker(handle.id, 1))

    events_path = tmp_path / "events.jsonl"
    assert wait_for(lambda: events_path.exists())

    def marker_lines() -> list:
        return [
            json.loads(line)
            for line in events_path.read_text().splitlines()
            if "marker" in line
        ]

    # Wait for both markers, then let several poll cycles (50 ms each) pass:
    # a poll thread without its own cursor would re-append them every cycle.
    assert wait_for(lambda: len(marker_lines()) == 2)
    time.sleep(0.3)
    assert len(marker_lines()) == 2
    markers = sorted(line["data"]["marker"] for line in marker_lines())
    assert markers == [0, 1]


# --------------------------------------------------------------------------- #
# The race itself — concurrent consumers lose no events
# --------------------------------------------------------------------------- #


def test_concurrent_consumers_lose_no_events(tmp_path):
    """A publisher, the ``Runtime.events`` reader, and the caps watchdog
    running concurrently: no event is lost or duplicated (pre-fix, the
    watchdog's drain stole events between the reader's polls)."""
    rt = make_runtime(settings=_settings(tmp_path, max_messages_per_step=1000))
    try:
        handle = rt.spawn("do it", driver=ScriptedDriver("complete('done')"))
        handle.await_()
        agent_id = handle.id
        topic = f"events:{agent_id}"

        # Pre-consume the agent's own lifecycle history so the reader below
        # sees only the markers the publisher races in.
        rt.events(agent_id)

        total = 200
        started = threading.Event()
        collected: list = []
        lock = threading.Lock()
        done = threading.Event()

        def publisher() -> None:
            started.wait()
            for i in range(total):
                rt.event_bus.publish(topic, _marker(agent_id, i))

        def events_reader() -> None:
            started.wait()
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                fresh = rt.events(agent_id)
                if fresh:
                    with lock:
                        collected.extend(fresh)
                if len(collected) >= total:
                    done.set()
                    return
                time.sleep(0.001)

        def watchdog() -> None:
            started.wait()
            step = 0
            while not done.is_set():
                step += 1
                rt._caps_watchdog(agent_id, rt.engine, step, time.monotonic())
                time.sleep(0.001)

        threads = [
            threading.Thread(target=publisher),
            threading.Thread(target=events_reader),
            threading.Thread(target=watchdog),
        ]
        for t in threads:
            t.start()
        started.set()
        for t in threads:
            t.join(15)
        assert not any(t.is_alive() for t in threads)

        # Every event received exactly once, in publish order.
        assert [e.payload["marker"] for e in collected] == list(range(total))
        # And nothing else leaked into the reader's stream.
        assert len(collected) == total
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# The wired path — the same fan-out through ``build_runtime``
# --------------------------------------------------------------------------- #


def test_wired_bus_peek_fan_out(tmp_path):
    """The fully-wired runtime (real EventBus behind ``_WiredBus``): the
    message-rate cap enabled in the pump does not steal the agent's events —
    the observe digest and the remaining bus events still cover every step."""
    from dhc.data.config import HarnessConfig, SafetyConfig, Settings
    from dhc.llm.driver import MockDriver
    from dhc.wiring import build_runtime

    settings = Settings(
        workspace_root=tmp_path,
        artifact_root=tmp_path,
        config=HarnessConfig(safety=SafetyConfig(max_messages_per_step=1000)),
    )
    rt = build_runtime(mock=True, artifact_root=tmp_path, settings=settings)
    rt.start()
    try:
        handle = rt.spawn("do it", driver=MockDriver(["complete('all good')"]))
        completion = handle.await_()
        assert completion.status.value == "completed"

        # The pump ran the watchdog every step with the cap enabled; the
        # events are still on the bus (peek is non-destructive there too).
        topic = f"events:{handle.id}"
        assert len(rt.event_bus.peek(topic)) > 0

        # The historical union still reconstructs every step exactly once
        # (a one-block MockDriver run is two pump steps: the block's step
        # and the settle step): the observe digest (consumed via
        # Runtime.events) plus the bus tail.
        ws = rt.repl_engine.globals_for(handle.id)
        digest = ws["state"]["digests"]["events"]
        bus_events = rt.events(handle.id)
        steps = [
            e.payload.get("step")
            for e in digest + bus_events
            if e.kind == EventKind.turn_started
        ]
        assert steps == [1, 2]
        kinds = [e.kind for e in digest + bus_events]
        assert EventKind.child_settled in kinds
    finally:
        rt.stop()
