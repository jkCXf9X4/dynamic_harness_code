"""Tests for the context-trigger seam (INFO-021).

Covers:
* :mod:`dhc.agent.context` — the digest observe/trim logic (the ONLY real
  pruning: keep the last 50 entries, drop older);
* the fabrication kit's ``observe`` delegate (identical semantics);
* the dormant :class:`~dhc.llm.llm.ContextRotDetector` wiring chain:
  ``build_runtime`` constructs it, the kit forwards it, and
  ``driver_from_settings`` feeds it to :class:`~dhc.llm.driver.LLMDriver`
  so the driver's existing per-block observation actually collects.
"""

import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc.agent.context import (  # noqa: E402
    DIGEST_KEEP,
    make_observe,
    observe_digest,
    trim_digest,
)
from dhc.llm.driver import (  # noqa: E402
    LLMDriver,
    MockDriver,
    driver_from_settings,
)
from dhc.llm.llm import ContextRotDetector, RotReport  # noqa: E402
from dhc.wiring import build_runtime  # noqa: E402
from dhc.llm.fabrication import fabrication_kit  # noqa: E402

# --------------------------------------------------------------------------- #
# trim_digest / observe_digest — the trim-50 contract
# --------------------------------------------------------------------------- #


class TestTrimDigest:
    def test_keeps_last_50(self):
        digest = list(range(60))
        trim_digest(digest)
        assert digest == list(range(10, 60))

    def test_shorter_than_keep_untouched(self):
        digest = list(range(30))
        trim_digest(digest)
        assert digest == list(range(30))

    def test_exactly_50_untouched(self):
        digest = list(range(50))
        trim_digest(digest)
        assert digest == list(range(50))

    def test_custom_keep(self):
        digest = list(range(10))
        trim_digest(digest, keep=3)
        assert digest == [7, 8, 9]

    def test_empty_digest(self):
        digest = []
        trim_digest(digest)
        assert digest == []

    def test_returns_digest(self):
        digest = list(range(60))
        assert trim_digest(digest) is digest

    def test_digest_keep_is_50(self):
        assert DIGEST_KEEP == 50

    def test_keep_zero_returns_empty(self):
        """keep=0 must drop everything (H-01: ``del digest[:-0]`` was a no-op)."""
        digest = list(range(10))
        out = trim_digest(digest, keep=0)
        assert out == []
        assert out is digest  # still in place

    def test_keep_zero_empty_digest(self):
        digest = []
        assert trim_digest(digest, keep=0) is digest
        assert digest == []

    def test_negative_keep_sanitized_to_zero(self):
        digest = list(range(10))
        assert trim_digest(digest, keep=-3) == []

    def test_none_keep_sanitized_to_zero(self):
        digest = list(range(10))
        assert trim_digest(digest, keep=None) == []


class TestObserveDigest:
    def test_extends_and_trims(self):
        state = {}
        events = list(range(60))
        observe_digest(state, events)
        assert state["digests"]["events"] == list(range(10, 60))

    def test_returns_fresh_events(self):
        state = {"digests": {"events": []}}
        events = ["a", "b"]
        assert observe_digest(state, events) is events

    def test_creates_nested_state_lazily(self):
        state = {}
        observe_digest(state, [])
        assert state["digests"]["events"] == []

    def test_accumulates_across_calls(self):
        state = {}
        observe_digest(state, list(range(30)))
        observe_digest(state, list(range(30, 60)))
        assert state["digests"]["events"] == list(range(10, 60))

    def test_custom_keep(self):
        state = {}
        observe_digest(state, list(range(10)), keep=3)
        assert state["digests"]["events"] == [7, 8, 9]

    def test_keep_zero_drops_all(self):
        state = {}
        observe_digest(state, list(range(10)), keep=0)
        assert state["digests"]["events"] == []


# --------------------------------------------------------------------------- #
# make_observe — the fabrication kit's delegate
# --------------------------------------------------------------------------- #


class TestMakeObserve:
    def test_delegate_matches_historical_semantics(self):
        """Drain + fetch + extend + trim-50, returning the fresh events."""
        drained = []
        state = {}
        observe = make_observe(
            lambda: drained.append("d"),
            lambda: ["e1", "e2"],
            state,
        )
        result = observe()
        assert drained == ["d"]
        assert result == ["e1", "e2"]
        assert state["digests"]["events"] == ["e1", "e2"]

    def test_trim_50_on_delegate(self):
        state = {}
        observe = make_observe(lambda: None, lambda: list(range(60)), state)
        observe()
        assert state["digests"]["events"] == list(range(10, 60))

    def test_repeated_calls_accumulate_and_trim(self):
        state = {}
        observe = make_observe(
            lambda: None,
            lambda: [f"e{i}" for i in range(30)],
            state,
        )
        observe()
        observe()
        # 30 + 30 = 60 entries -> trim to the last 50: the first batch's
        # tail (e10..e29) followed by the whole second batch (e0..e29).
        assert state["digests"]["events"] == (
            [f"e{i}" for i in range(10, 30)] + [f"e{i}" for i in range(30)]
        )


# --------------------------------------------------------------------------- #
# The dormant detector wiring chain (observe-only)
# --------------------------------------------------------------------------- #


class _SpyDetector:
    """Observe-only detector double: records texts, never prunes."""

    def __init__(self):
        self.seen = []

    def observe(self, text):
        self.seen.append(text)
        return RotReport(rot=False, score=0.0, signals=[])


class TestDetectorWiring:
    def test_build_runtime_constructs_detector(self, tmp_path):
        rt = build_runtime(mock=True, artifact_root=str(tmp_path))
        try:
            assert isinstance(rt.rot_detector, ContextRotDetector)
        finally:
            rt.stop()

    def test_kit_forwards_detector_to_factory(self, tmp_path, monkeypatch):
        """fabrication_kit passes runtime.rot_detector into
        driver_from_settings, which feeds it to the LLMDriver."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        rt = build_runtime(mock=False, artifact_root=str(tmp_path))
        try:
            agent = _register_agent(rt)
            engine = rt.repl_engine
            kit = fabrication_kit(rt, engine, agent)
            driver = kit["state"]["_driver"]
            assert isinstance(driver, LLMDriver)
            assert driver._rot_detector is rt.rot_detector
        finally:
            rt.stop()

    def test_driver_observes_each_block(self, tmp_path, monkeypatch):
        """LLMDriver.__call__'s existing per-block observation collects
        into the wired detector (observe-only: nothing prunes)."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        rt = build_runtime(mock=False, artifact_root=str(tmp_path))
        try:
            agent = _register_agent(rt)
            engine = rt.repl_engine
            kit = fabrication_kit(rt, engine, agent)
            driver = kit["state"]["_driver"]
            driver._client = _SpyClient()
            code = driver(agent)
            assert code == "def action():\n    return 1"
            # The real ContextRotDetector has no public .seen; it stores
            # observed blocks in its rolling window. Verify the wired
            # detector collected the block (observe-only).
            assert list(driver._rot_detector._window) == [code]
        finally:
            rt.stop()

    def test_detector_never_prunes(self, tmp_path, monkeypatch):
        """The rot detector is observe-only: a rot report must not change
        the driver's return value or pruning behavior."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        rt = build_runtime(mock=False, artifact_root=str(tmp_path))
        try:
            agent = _register_agent(rt)
            engine = rt.repl_engine
            kit = fabrication_kit(rt, engine, agent)
            driver = kit["state"]["_driver"]
            rotting = "failed failed failed failed"
            driver._client = _SpyClient(rotting)
            driver._rot_detector = _RottingDetector()
            code = driver(agent)
            assert code == rotting  # block returned unchanged
        finally:
            rt.stop()

    def test_factory_kwarg_real_path(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        detector = ContextRotDetector()
        driver = driver_from_settings(mock=False, rot_detector=detector)
        assert isinstance(driver, LLMDriver)
        assert driver._rot_detector is detector

    def test_factory_kwarg_mock_path_ignores_detector(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        driver = driver_from_settings(mock=True, rot_detector=ContextRotDetector())
        assert isinstance(driver, MockDriver)
        assert not hasattr(driver, "_rot_detector")

    def test_factory_default_no_detector(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        driver = driver_from_settings(mock=False)
        assert isinstance(driver, LLMDriver)
        assert driver._rot_detector is None


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _register_agent(rt, agent_id="a1", requirement="r"):
    """Register an agent on the runtime WITHOUT starting a worker thread
    (the same bookkeeping spawn does, minus the thread)."""
    from dhc.agent.agent import Agent, AgentHandle

    agent = Agent(
        id=agent_id,
        requirement=requirement,
        runtime=rt,
    )
    rt._agents[agent_id] = agent
    rt._handles[agent_id] = AgentHandle(agent_id, rt)
    rt._stop_flags[agent_id] = threading.Event()
    return agent


class _SpyClient:
    """Fake LLM client: returns one fixed block, no network."""

    def __init__(self, code="def action():\n    return 1"):
        self._code = code

    def generate_code_block(self, prompt, context):
        return self._code


class _RottingDetector:
    """Detector double that always reports rot (observe-only)."""

    def observe(self, text):
        return RotReport(rot=True, score=1.0, signals=["repetition"])


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    """Point XDG discovery at tmp_path and reset the settings singleton.

    Mirrors tests/llm/test_llm.py so a real user config or a previous test
    can never leak into provider-default assertions.
    """
    from dhc.data import config as config_mod

    monkeypatch.setattr(
        config_mod, "XDG_CONFIG_DIR", tmp_path / ".config" / "dynamic-harness"
    )
    monkeypatch.setattr(config_mod, "_settings", None)
    yield
    monkeypatch.setattr(config_mod, "_settings", None)
