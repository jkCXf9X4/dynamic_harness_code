"""Tests for dhc.llm — LLM client, mock path, context-rot detection.

No real network calls anywhere: the real client is only exercised with an
injected fake openai client (timeout containment) or never constructed
(available/lazy tests).
"""

from __future__ import annotations

import time
from pathlib import Path

import httpx
import openai
import pytest

import dhc.data.config as config_mod
from dhc import errors
from dhc.data.config import merge_api_key
from dhc.llm.driver import (
    EMPTY_COMPLETION_RETRIES,
    LLMDriver,
    MockDriver,
    driver_from_settings,
)
from dhc.llm.llm import (
    ContextRotDetector,
    LLMClient,
    LLMConfig,
    LLMProvider,
    LLMResponse,
    MockLLM,
    OpenAIProvider,
    RotReport,
)


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    """Point XDG discovery at tmp_path and reset the settings singleton.

    Mirrors tests/test_config.py so a real user config or a previous test can
    never leak into provider-default assertions.
    """
    monkeypatch.setattr(
        config_mod, "XDG_CONFIG_DIR", tmp_path / ".config" / "dynamic-harness"
    )
    monkeypatch.setattr(config_mod, "_settings", None)
    yield
    monkeypatch.setattr(config_mod, "_settings", None)


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

# ---------------------------------------------------------------------------
# OpenAIProvider — defaults, key precedence, retries, routing, timeout
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, prompt_tokens=10, completion_tokens=5, cost=None):
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens
        self.prompt_tokens_details = None
        self.cost = cost


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content, usage=None):
        self.choices = [_FakeChoice(content)]
        self.usage = usage


class _FakeCompletions:
    """Scripted fake: each call pops the next result/exception from the queue."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.kwargs_list = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        self.kwargs_list.append(kwargs)
        if not self.script:
            raise AssertionError("fake exhausted")
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeOpenAI:
    def __init__(self, completions):
        self.chat = _FakeChat(completions)
        self.closed = False

    def close(self):
        self.closed = True


def _inject_fake(provider, completions):
    """Inject a fake openai client into the provider (no network)."""
    provider._client = _FakeOpenAI(completions)
    return completions


def _rate_limit_error():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    response = httpx.Response(429, request=request)
    return openai.RateLimitError(
        "rate limit exceeded", response=response, body=None
    )


def _timeout_error():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return openai.APITimeoutError(request=request)


def _connection_error():
    request = httpx.Request("POST", "https://openrouter.ai/api/v1/chat/completions")
    return openai.APIConnectionError(message="connection dropped", request=request)


class TestOpenAIProviderDefaults:
    def test_defaults_come_from_config(self, monkeypatch):
        """Model/base_url default to the OpenRouter config values."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider()
        assert provider.default_model == "deepseek/deepseek-v4-flash"
        assert provider._base_url == "https://openrouter.ai/api/v1"
        assert provider._is_openrouter is True
        assert provider.timeout == 500.0
        assert provider.max_retries == 4
        assert provider.rate_limit_max_attempts == 6
        assert provider.retry_base_delay_seconds == 1.0
        assert provider.retry_max_delay_seconds == 30.0
        assert provider.retry_jitter_seconds == 0.5
        assert provider.rate_limit_backoff_multiplier == 3.0
        assert provider.fallback_on_rate_limit is True

    def test_explicit_args_override_config(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider(
            model="custom-model",
            base_url="https://custom.example/v1",
            timeout=10.0,
            max_retries=2,
        )
        assert provider.default_model == "custom-model"
        assert provider._base_url == "https://custom.example/v1"
        assert provider._is_openrouter is False
        assert provider.timeout == 10.0
        assert provider.max_retries == 2

    def test_available_reflects_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert OpenAIProvider().available() is False
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        assert OpenAIProvider().available() is True

    def test_generate_without_key_raises_turn_error(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        provider = OpenAIProvider()
        with pytest.raises(errors.TurnError):
            provider.generate("system", "user")


class TestMergeApiKeyPrecedence:
    def test_openrouter_wins_over_openai(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa")
        assert merge_api_key() == "sk-or"

    def test_openai_fallback(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa")
        assert merge_api_key() == "sk-oa"

    def test_none_without_env(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert merge_api_key() is None

    def test_provider_uses_merge_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa")
        assert OpenAIProvider()._api_key == "sk-oa"
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        assert OpenAIProvider()._api_key == "sk-or"


class TestOpenAIProviderRetries:
    def test_retries_transient_then_succeeds(self, monkeypatch):
        """A transient failure is retried; the next attempt succeeds."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider(
            max_retries=4,
            retry_base_delay_seconds=0.0,
            retry_jitter_seconds=0.0,
        )
        completions = _FakeCompletions(
            [
                _connection_error(),
                _FakeResponse("```python\nreturn 1\n```", usage=_FakeUsage()),
            ]
        )
        _inject_fake(provider, completions)
        response = provider.generate("system", "user")
        assert response.text == "```python\nreturn 1\n```"
        assert len(completions.calls) == 2

    def test_retries_rate_limit_then_succeeds(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider(
            max_retries=4,
            rate_limit_max_attempts=6,
            retry_base_delay_seconds=0.0,
            retry_jitter_seconds=0.0,
        )
        completions = _FakeCompletions(
            [
                _rate_limit_error(),
                _FakeResponse("return 2", usage=_FakeUsage()),
            ]
        )
        _inject_fake(provider, completions)
        response = provider.generate("system", "user")
        assert response.text == "return 2"
        assert len(completions.calls) == 2

    def test_raises_turn_error_after_exhausting_retries(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider(
            max_retries=2,
            retry_base_delay_seconds=0.0,
            retry_jitter_seconds=0.0,
        )
        completions = _FakeCompletions(
            [_connection_error(), _connection_error(), _connection_error()]
        )
        _inject_fake(provider, completions)
        with pytest.raises(errors.TurnError):
            provider.generate("system", "user")
        assert len(completions.calls) == 2  # 1 attempt + 1 retry

    def test_non_retryable_error_raises_immediately(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider(max_retries=4)
        completions = _FakeCompletions([RuntimeError("boom")])
        _inject_fake(provider, completions)
        with pytest.raises(errors.TurnError):
            provider.generate("system", "user")
        assert len(completions.calls) == 1

    def test_timeout_raises_turn_timeout_without_retry(self, monkeypatch):
        """A watchdog timeout is never retried — it surfaces immediately."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider(timeout=0.2, max_retries=4)

        class SleepingCompletions:
            def create(self, **kwargs):
                time.sleep(30)
                raise AssertionError("should never return")

        class SleepingChat:
            completions = SleepingCompletions()

        class SleepingOpenAI:
            chat = SleepingChat()

            def close(self):
                pass

        provider._client = SleepingOpenAI()
        start = time.monotonic()
        with pytest.raises(errors.TurnTimeoutError):
            provider.generate("system", "user")
        elapsed = time.monotonic() - start
        assert elapsed < 5.0, f"timeout containment took {elapsed:.1f}s"


class TestOpenAIProviderRouting:
    def test_openrouter_extra_body_routing(self, monkeypatch):
        """provider_force/ignore/allow_fallbacks + session_id forwarded to
        OpenRouter."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider(
            provider_force="deepinfra",
            provider_ignore=["together"],
            provider_allow_fallbacks=False,
        )
        completions = _FakeCompletions(
            [_FakeResponse("ok", usage=_FakeUsage())]
        )
        _inject_fake(provider, completions)
        provider.generate(
            "system",
            "user",
            LLMConfig(session_id="sess-1"),
        )
        kwargs = completions.calls[0]
        extra = kwargs["extra_body"]
        assert extra["provider"]["order"] == ["deepinfra"]
        assert extra["provider"]["allow_fallbacks"] is False
        assert extra["provider"]["ignore"] == ["together"]
        assert extra["session_id"] == "sess-1"

    def test_openrouter_ignore_only(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider(provider_ignore=["together"])
        completions = _FakeCompletions(
            [_FakeResponse("ok", usage=_FakeUsage())]
        )
        _inject_fake(provider, completions)
        provider.generate("system", "user")
        extra = completions.calls[0]["extra_body"]
        assert extra["provider"]["ignore"] == ["together"]
        assert extra["provider"]["allow_fallbacks"] is True
        assert "session_id" not in extra

    def test_no_extra_body_when_nothing_configured(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider()
        completions = _FakeCompletions(
            [_FakeResponse("ok", usage=_FakeUsage())]
        )
        _inject_fake(provider, completions)
        provider.generate("system", "user")
        assert "extra_body" not in completions.calls[0]

    def test_no_extra_body_for_external_provider(self, monkeypatch):
        """Routing is OpenRouter-only: an external base_url gets no extra_body."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider(
            base_url="https://custom.example/v1",
            provider_force="deepinfra",
        )
        completions = _FakeCompletions(
            [_FakeResponse("ok", usage=_FakeUsage())]
        )
        _inject_fake(provider, completions)
        provider.generate("system", "user")
        assert "extra_body" not in completions.calls[0]

    def test_messages_and_temperature(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider()
        completions = _FakeCompletions(
            [_FakeResponse("ok", usage=_FakeUsage())]
        )
        _inject_fake(provider, completions)
        provider.generate("sys", "usr")
        kwargs = completions.calls[0]
        assert kwargs["model"] == "deepseek/deepseek-v4-flash"
        assert kwargs["temperature"] == 0.0
        assert kwargs["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "usr"},
        ]

    def test_response_carries_usage_and_cost(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        provider = OpenAIProvider(
            price_input_per_mtok=1.0,
            price_output_per_mtok=2.0,
        )
        completions = _FakeCompletions(
            [
                _FakeResponse(
                    "ok",
                    usage=_FakeUsage(prompt_tokens=1_000_000, completion_tokens=500_000),
                )
            ]
        )
        _inject_fake(provider, completions)
        response = provider.generate("system", "user")
        assert response.usage["prompt_tokens"] == 1_000_000
        assert response.usage["completion_tokens"] == 500_000
        assert response.cost_usd == pytest.approx(1.0 + 1.0)  # 1*1 + 0.5*2


class TestLLMClientWrapper:
    def test_wraps_provider_and_strips_fences(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        client = LLMClient(api_key="sk-test", model="fake-model", timeout_seconds=5.0)
        completions = _FakeCompletions(
            [_FakeResponse("```python\nreturn 1\n```", usage=_FakeUsage())]
        )
        _inject_fake(client._provider, completions)
        assert client.generate_code_block("do something") == "return 1"
        kwargs = completions.calls[0]
        assert kwargs["model"] == "fake-model"
        assert kwargs["messages"][0]["role"] == "system"
        assert kwargs["messages"][1]["role"] == "user"
        assert "do something" in kwargs["messages"][1]["content"]

    def test_close_releases_client(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        client = LLMClient(api_key="sk-test")
        fake = _FakeOpenAI(_FakeCompletions([]))
        client._provider._client = fake
        client.close()
        assert fake.closed is True
        assert client._provider._client is None


class TestDriverFromSettingsProvider:
    def test_picks_llm_driver_with_key(self, monkeypatch):
        """With a key present, the factory returns an LLMDriver over an
        OpenAIProvider (model/base_url/timeout from settings.provider)."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        driver = driver_from_settings(mock=False)
        assert isinstance(driver, LLMDriver)
        client = driver._client
        assert isinstance(client, LLMClient)
        provider = client._provider
        assert isinstance(provider, OpenAIProvider)
        assert provider.default_model == "deepseek/deepseek-v4-flash"
        assert provider._base_url == "https://openrouter.ai/api/v1"
        assert provider.timeout == 500.0

    def test_picks_mock_driver_without_key(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        driver = driver_from_settings(mock=False)
        assert isinstance(driver, MockDriver)

    def test_mock_flag_forces_mock(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        driver = driver_from_settings(mock=True)
        assert isinstance(driver, MockDriver)

    def test_mockllm_path_unchanged(self):
        """The documented mock path still works end-to-end."""
        mock = MockLLM({"def action": "def action():\n    return 1"})
        assert mock.generate_code_block("please write def action") == (
            "def action():\n    return 1"
        )
        assert mock.available() is True
        mock.close()


# --------------------------------------------------------------------------- #
# INFO-020 hardening — empty completion + turn cap fail diagnostically
# --------------------------------------------------------------------------- #


class _ScriptClient:
    """Fake LLM client returning a fixed sequence of blocks (None = settle
    signal, the scripted-client contract), with a call counter."""

    def __init__(self, blocks):
        self._blocks = list(blocks)
        self.calls = 0

    def generate_code_block(self, prompt, context):
        self.calls += 1
        if self.calls > len(self._blocks):
            return None
        return self._blocks[self.calls - 1]


def _bare_agent():
    from dhc.framework.agent import Agent

    return Agent(id="a1", requirement="req")


class TestEmptyCompletionFailsDiagnostically:
    def test_empty_completion_fails_with_diagnostic_reason(self):
        """A client that always returns blank blocks: the driver retries
        in-call (EMPTY_COMPLETION_RETRIES), then returns a fail() block
        naming the cause — never a silent None settle."""
        agent = _bare_agent()
        client = _ScriptClient(["", "   ", "\n"])
        driver = LLMDriver(client)
        code = driver(agent)
        assert code is not None
        assert "empty completion after" in code
        assert "fail(" in code
        # Bounded: one initial call + EMPTY_COMPLETION_RETRIES retries.
        assert client.calls == 1 + EMPTY_COMPLETION_RETRIES
        # The fail-once pattern: the next call settles (None), it does not
        # keep retrying or looping.
        assert driver(agent) is None

    def test_retry_recovers_non_empty_block(self):
        """A blank block followed by a real one: the retry succeeds, the
        block is returned normally, and the retries did not consume the
        turn cap (one __call__ = one turn)."""
        agent = _bare_agent()
        client = _ScriptClient(["", "x = 1\n"])
        driver = LLMDriver(client, max_turns=1)
        assert driver(agent) == "x = 1\n"
        assert client.calls == 2  # one blank + one retry
        # The retry did not consume the cap: the next call is the cap, not
        # an early settle.
        code = driver(agent)
        assert code is not None
        assert "turn cap reached" in code

    def test_none_return_still_settles(self):
        """A scripted client returning None (script exhausted) still settles
        the agent — None remains the documented settle signal, distinct
        from a blank-block completion."""
        agent = _bare_agent()
        client = _ScriptClient(["complete('done')\n"])
        driver = LLMDriver(client)
        assert driver(agent) == "complete('done')\n"
        assert driver(agent) is None


class TestTurnCapFailsDiagnostically:
    def test_cap_fails_with_reason_naming_the_cap(self):
        """Cap exhaustion returns a fail() block naming the cap (distinct
        from a model stop), then settles on the next call."""
        agent = _bare_agent()
        client = _ScriptClient(["x = 1\n"] * 10)
        driver = LLMDriver(client, max_turns=2)
        assert driver(agent) == "x = 1\n"
        assert driver(agent) == "x = 1\n"
        code = driver(agent)
        assert code is not None
        assert "turn cap reached" in code
        assert "2/2" in code
        assert "fail(" in code
        # Fail-once: the next call settles.
        assert driver(agent) is None

    def test_cap_does_not_shadow_prior_failure(self):
        """A client failure followed by cap exhaustion: the failure settles
        first (the _failed_once check runs before the cap check, so a
        fail-once agent cannot be re-failed by the cap)."""
        agent = _bare_agent()

        class _Boom:
            def generate_code_block(self, prompt, context):
                raise RuntimeError("boom")

        driver = LLMDriver(_Boom(), max_turns=1)
        first = driver(agent)
        assert first is not None and "LLM call failed" in first
        assert driver(agent) is None  # settles, not re-failed by the cap


class TestDriverFromSettingsMaxTurns:
    def test_plumbs_max_turns_from_agent_config(self, monkeypatch):
        """driver_from_settings reads settings.config.agent.max_turns and
        passes it to LLMDriver (harness.json agent.max_turns -> LLMDriver)."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        settings = config_mod.Settings(
            workspace_root=Path("/tmp"),
            artifact_root=Path("/tmp"),
            config=config_mod.HarnessConfig(
                agent=config_mod.AgentConfig(max_turns=7)
            ),
        )
        driver = driver_from_settings(settings, mock=False)
        assert isinstance(driver, LLMDriver)
        assert driver._max_turns == 7

    def test_default_max_turns_is_20(self, monkeypatch):
        """Backward compatibility: with no agent.max_turns configured, the
        driver keeps the historical default cap of 20."""
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        driver = driver_from_settings(mock=False)
        assert isinstance(driver, LLMDriver)
        assert driver._max_turns == 20

    def test_agent_config_default_is_20(self):
        """The AgentConfig field default is 20 (the constructor default and
        the config default agree)."""
        assert config_mod.AgentConfig().max_turns == 20
        assert config_mod.HarnessConfig().agent.max_turns == 20
