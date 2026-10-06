"""Tests for dhc.llm — LLM client, mock path, context-rot detection.

No real network calls anywhere: the real client is only exercised with an
injected fake openai client (timeout containment) or never constructed
(available/lazy tests).
"""

from __future__ import annotations

import time

import pytest

from dhc import errors
from dhc.llm import ContextRotDetector, LLMClient, MockLLM, RotReport


# ---------------------------------------------------------------------------
# MockLLM — documented mock path
# ---------------------------------------------------------------------------


class TestMockLLM:
    def test_returns_matched_block(self):
        mock = MockLLM({"def action": "def action():\n    return 1"})
        assert mock.generate_code_block("please write def action now") == (
            "def action():\n    return 1"
        )

    def test_returns_default_when_no_match(self):
        mock = MockLLM({"def action": "def action():\n    return 1"}, default="pass")
        assert mock.generate_code_block("write something else") == "pass"

    def test_strips_markdown_fences(self):
        mock = MockLLM(
            {"action": "```python\ndef action():\n    return 1\n```"},
            default="```\npass\n```",
        )
        assert mock.generate_code_block("give me the action") == (
            "def action():\n    return 1"
        )
        assert mock.generate_code_block("nothing matches") == "pass"

    def test_callable_mode(self):
        mock = MockLLM(fn=lambda prompt, context: f"# {prompt}\nreturn 42")
        assert mock.generate_code_block("go") == "# go\nreturn 42"

    def test_same_interface_as_llm_client(self):
        mock = MockLLM({"x": "y"})
        assert mock.available() is True
        mock.close()  # no-op, must not raise


# ---------------------------------------------------------------------------
# LLMClient — lazy, available, timeout containment
# ---------------------------------------------------------------------------


class TestLLMClient:
    def test_available_false_without_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = LLMClient(api_key="")
        assert client.available() is False

    def test_available_true_with_key(self):
        client = LLMClient(api_key="sk-test")
        assert client.available() is True

    def test_lazy_construction_without_key_does_not_raise(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = LLMClient(api_key="")
        # Constructing must not touch the network or require a key.
        client.close()

    def test_generate_without_key_raises_turn_error(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        client = LLMClient(api_key="")
        with pytest.raises(errors.TurnError):
            client.generate_code_block("do something")

    def test_timeout_containment_no_hang(self):
        """A sleeping fake openai client must surface TurnTimeoutError quickly."""
        client = LLMClient(
            api_key="sk-test",
            model="fake-model",
            timeout_seconds=0.2,
        )

        class FakeCompletions:
            def create(self, **kwargs):
                time.sleep(30)
                raise AssertionError("should never return")

        class FakeChat:
            completions = FakeCompletions()

        class FakeOpenAI:
            chat = FakeChat()

            def close(self):
                pass

        client._client = FakeOpenAI()
        start = time.monotonic()
        with pytest.raises(errors.TurnTimeoutError):
            client.generate_code_block("do something")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"timeout containment took {elapsed:.1f}s"

    def test_other_failure_raises_turn_error(self):
        client = LLMClient(
            api_key="sk-test",
            model="fake-model",
            timeout_seconds=5.0,
        )

        class FakeCompletions:
            def create(self, **kwargs):
                raise RuntimeError("boom")

        class FakeChat:
            completions = FakeCompletions()

        class FakeOpenAI:
            chat = FakeChat()

            def close(self):
                pass

        client._client = FakeOpenAI()
        with pytest.raises(errors.TurnError):
            client.generate_code_block("do something")

    def test_success_strips_fences(self):
        client = LLMClient(
            api_key="sk-test",
            model="fake-model",
            timeout_seconds=5.0,
        )

        class FakeCompletions:
            def create(self, **kwargs):
                assert kwargs["model"] == "fake-model"
                assert kwargs["messages"][0]["role"] == "system"
                assert kwargs["messages"][1]["role"] == "user"
                assert "do something" in kwargs["messages"][1]["content"]
                return _FakeResponse("```python\nreturn 1\n```")

        class FakeChat:
            completions = FakeCompletions()

        class FakeOpenAI:
            chat = FakeChat()

            def close(self):
                pass

        client._client = FakeOpenAI()
        assert client.generate_code_block("do something") == "return 1"


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeMessage:
    def __init__(self, content):
        self.content = content


# ---------------------------------------------------------------------------
# ContextRotDetector — INFO-021
# ---------------------------------------------------------------------------


class TestContextRotDetector:
    def test_passes_normal_text(self):
        detector = ContextRotDetector()
        text = (
            "The agent inspected the artifact store, found the missing report, "
            "and wrote a corrected summary to the workspace."
        )
        report = detector.detect(text)
        assert isinstance(report, RotReport)
        assert report.rot is False
        assert 0.0 <= report.score <= 1.0

    def test_flags_repetition(self):
        detector = ContextRotDetector()
        text = "do the thing do the thing do the thing do the thing do the thing"
        report = detector.detect(text)
        assert report.rot is True
        assert "repetition" in report.signals

    def test_flags_degenerate_short_output(self):
        detector = ContextRotDetector(min_length=50)
        report = detector.detect("ok")
        assert report.rot is True
        assert "degenerate_length" in report.signals

    def test_flags_degenerate_length_vs_expected(self):
        detector = ContextRotDetector(expected_length=200)
        assert detector.detect("tiny").rot is True
        assert detector.detect("x" * 500).rot is True
        assert detector.detect("x" * 200).rot is False

    def test_flags_repeated_failure_phrases(self):
        detector = ContextRotDetector()
        text = "Error: failed. Traceback: exception. I can't continue."
        report = detector.detect(text)
        assert report.rot is True
        assert "repeated_failure_phrases" in report.signals

    def test_window_updates_novelty(self):
        detector = ContextRotDetector(threshold=0.6)
        text = "the quick brown fox jumps over the lazy dog"
        assert detector.detect(text).rot is False
        detector.observe(text)
        # Near-identical output after observing the same text -> low novelty.
        report = detector.observe(text)
        assert report.rot is True
        assert "low_novelty" in report.signals

    def test_window_rolls_off(self):
        detector = ContextRotDetector(window_size=2, threshold=0.6)
        text = "the quick brown fox jumps over the lazy dog"
        detector.observe(text)
        detector.observe("a completely different sentence about cats and hats")
        detector.observe("quantum entanglement confuses many physicists today")
        # The original text has rolled out of the 2-slot window; a repeat of
        # it is no longer low-novelty against the window.
        report = detector.observe(text)
        assert "low_novelty" not in report.signals

    def test_threshold_configurable(self):
        detector = ContextRotDetector(threshold=1.0)
        text = "do the thing do the thing do the thing do the thing do the thing"
        assert detector.detect(text).rot is False  # score < 1.0 threshold
        assert detector.detect(text).score > 0.0