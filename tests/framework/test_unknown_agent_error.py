"""W4.3 + W4.5: UnknownAgentError and the read-only inspection helpers.

W4.3 — the runtime's supervision paths raise :class:`UnknownAgentError`
(a named :class:`DhcError`) instead of a bare ``KeyError`` when given an
agent id the runtime does not know. The message names the offending id AND
how many agents the runtime actually knows, so a typo or a stale id fails
loudly and diagnosably (F10).

W4.5 — the runtime exposes three public, read-only helpers so tests and
hosts can inspect the registry / stop flags / caps watchdog without
reaching into privates: :meth:`Runtime.agents_snapshot`,
:meth:`Runtime.is_stopped`, :meth:`Runtime.caps_state`. Each returns a
copy (or a value) the caller cannot use to mutate the runtime.
"""

import threading
import time

import pytest

from dhc.data.models import AgentStatus
from dhc.errors import DhcError, UnknownAgentError
from dhc.framework.agent import Agent
from dhc.framework.runtime import Runtime


class ScriptedDriver:
    """A driver that replays a fixed script of code blocks, then settles."""

    def __init__(self, *blocks: str) -> None:
        self.blocks = list(blocks)
        self.calls = 0

    def __call__(self, agent: Agent):
        if self.calls >= len(self.blocks):
            return None
        code = self.blocks[self.calls]
        self.calls += 1
        return code


class BlockingDriver:
    """A driver that blocks on the first call until released."""

    def __init__(self) -> None:
        self.release = threading.Event()

    def __call__(self, agent: Agent):
        self.release.wait(timeout=30)
        return None


def wait_for(predicate, timeout: float = 10.0) -> bool:
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


# --------------------------------------------------------------------------- #
# W4.3 — UnknownAgentError
# --------------------------------------------------------------------------- #


def test_unknown_agent_error_is_a_dhc_error():
    assert issubclass(UnknownAgentError, DhcError)
    assert issubclass(UnknownAgentError, Exception)


def test_unknown_agent_error_message_names_id_and_count():
    err = UnknownAgentError("unknown agent id 'nope' (runtime knows 2 agents)")
    assert "nope" in str(err)
    assert "2" in str(err)


def test_all_seven_paths_raise_unknown_agent_error():
    """Every unknown-agent supervision path raises UnknownAgentError, and
    the message carries the offending id and the known-agent count."""
    rt = make_runtime()
    try:
        # Seed one known agent so the count is non-trivial (1).
        handle = rt.spawn("do it", driver=ScriptedDriver("complete('done')"))
        handle.await_()
        known = handle.id

        # The known id must NOT raise (sanity: the error is specific).
        assert rt.poll(known) == AgentStatus.completed

        for path in (
            lambda: rt.poll("nope"),
            lambda: rt.await_("nope"),
            lambda: rt.cancel("nope"),
            lambda: rt.result("nope"),
            lambda: rt.get("nope"),
            lambda: rt.children_of("nope"),
            lambda: rt.is_settled("nope"),
        ):
            with pytest.raises(UnknownAgentError) as exc:
                path()
            msg = str(exc.value)
            assert "nope" in msg, f"id missing from message: {msg!r}"
            assert "1" in msg, f"known-agent count missing from message: {msg!r}"
    finally:
        rt.stop()


def test_unknown_agent_error_count_reflects_registry_size():
    """The count in the message tracks the live registry size."""
    rt = make_runtime()
    try:
        h1 = rt.spawn("a", driver=ScriptedDriver("complete('x')"))
        h2 = rt.spawn("b", driver=ScriptedDriver("complete('y')"))
        h1.await_()
        h2.await_()
        with pytest.raises(UnknownAgentError) as exc:
            rt.poll("ghost")
        assert "2" in str(exc.value)
    finally:
        rt.stop()


def test_unknown_agent_error_is_not_keyerror():
    """The named error is NOT a KeyError (it is a DhcError), so callers
    catching DhcError get it, and KeyError handlers no longer fire."""
    rt = make_runtime()
    try:
        with pytest.raises(UnknownAgentError):
            rt.poll("nope")
        # And it must not be silently caught as a KeyError.
        try:
            rt.poll("nope")
        except KeyError:  # pragma: no cover - must not be reached
            pytest.fail("UnknownAgentError leaked as a bare KeyError")
        except UnknownAgentError:
            pass
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# W4.5 — read-only inspection helpers
# --------------------------------------------------------------------------- #


def test_agents_snapshot_is_a_copy():
    """agents_snapshot() returns a copy: mutating it does NOT affect the
    runtime's registry, and the runtime's registry is not the same object."""
    rt = make_runtime()
    try:
        h1 = rt.spawn("a", driver=ScriptedDriver("complete('x')"))
        h1.await_()

        snap = rt.agents_snapshot()
        assert set(snap) == {h1.id}
        assert snap[h1.id] is rt.get(h1.id)  # same Agent object (shallow copy)

        # Mutating the returned dict must not touch the runtime.
        snap["injected"] = object()
        snap.pop(h1.id)
        assert h1.id in rt.agents_snapshot()
        assert "injected" not in rt.agents_snapshot()

        # And it is a distinct object from the private registry.
        assert snap is not rt._agents
    finally:
        rt.stop()


def test_agents_snapshot_empty_before_spawn():
    rt = make_runtime()
    try:
        assert rt.agents_snapshot() == {}
    finally:
        rt.stop()


def test_is_stopped_reflects_stop_flag():
    """is_stopped() is False for a live agent and True once cancelled."""
    rt = make_runtime()
    try:
        # A blocking driver keeps the agent live so we can observe the flag.
        blocking = BlockingDriver()
        handle = rt.spawn("b", driver=blocking)
        # Wait until the worker has started (agent is live, not yet stopped).
        assert wait_for(lambda: not rt.is_stopped(handle.id))
        assert rt.is_stopped(handle.id) is False
        rt.cancel(handle.id, reason="stop now")
        assert wait_for(lambda: rt.is_stopped(handle.id))
        assert rt.is_stopped(handle.id) is True
        blocking.release.set()  # unblock the worker so stop() can join
    finally:
        rt.stop()


def test_is_stopped_unknown_agent_raises():
    rt = make_runtime()
    try:
        with pytest.raises(UnknownAgentError):
            rt.is_stopped("nope")
    finally:
        rt.stop()


def test_caps_state_is_a_copy():
    """caps_state() returns a copy of the watchdog cursors: mutating it
    does NOT affect the watchdog's live state."""
    rt = make_runtime()
    try:
        # Seed a cursor the way the watchdog does, then read it back.
        rt._caps_cursors["seeded"] = 7
        state = rt.caps_state()
        assert state == {"seeded": 7}

        # Mutating the returned dict must not touch the live cursors.
        state["injected"] = 99
        state.pop("seeded")
        assert rt.caps_state() == {"seeded": 7}
        assert state is not rt._caps_cursors
    finally:
        rt.stop()


def test_caps_state_empty_by_default():
    rt = make_runtime()
    try:
        assert rt.caps_state() == {}
    finally:
        rt.stop()
