"""LLM integration for dhc — provider abstraction, mock path, context-rot detection.

INFO-020 (timeout containment): every LLM call is bounded by ``timeout``. A
call that exceeds the budget raises :class:`errors.TurnTimeoutError` (never
hangs); any other failure raises :class:`errors.TurnError`, so the runtime can
surface a failed turn without hanging or crashing the agent.

INFO-021 (context-rot detection): :class:`ContextRotDetector` scores an agent
output stream for degradation signatures — n-gram repetition, degenerate
length, repeated failure phrases, and low novelty against a rolling window of
recent outputs.

Provider pattern (reference-aligned): :class:`LLMProvider` is the abstract
interface; :class:`OpenAIProvider` is the sole concrete implementation,
wrapping the sync ``openai.OpenAI`` SDK (dhc's engine is thread-based, so the
provider is sync — the reference's async machinery is not ported). The default
provider is OpenRouter (``base_url https://openrouter.ai/api/v1``, model
``deepseek/deepseek-v4-flash`` from config); external OpenAI-compatible
providers are enabled by passing a different ``base_url``. OpenRouter routing
(``provider_force`` / ``provider_ignore`` / ``provider_allow_fallbacks``) and
``session_id`` are forwarded via ``extra_body`` only when the base_url contains
"openrouter". Retries follow the configured retry/rate-limit policy with
exponential backoff + jitter; on final failure the call raises
:class:`errors.TurnError`.

Mock path (documented): :class:`MockLLM` is a deterministic fake with the same
interface as :class:`LLMClient`. Use it in tests and demos instead of the real
client::

    mock = MockLLM({"def action": "def action():\\n    return 1"})
    code = mock.generate_code_block("please write def action")
"""

from __future__ import annotations

import random
import re
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Mapping, Optional

import openai

from . import errors
from .config import get_settings, merge_api_key

_SYSTEM_PROMPT = (
    "You are the action generator for a recursive agent runtime. "
    "Respond with ONLY a single Python code block containing the next action "
    "to execute. No prose, no explanation, no markdown outside the code block."
)


def _strip_markdown_fences(code: str) -> str:
    """Strip a surrounding ```lang ... ``` fence from *code*."""
    code = code.strip()
    if not code.startswith("```"):
        return code
    lines = code.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Provider abstraction
# ---------------------------------------------------------------------------


@dataclass
class LLMConfig:
    """Per-call configuration passed to :meth:`LLMProvider.generate`."""

    model: Optional[str] = None
    temperature: float = 0.0
    max_tokens: Optional[int] = None
    provider_ignore: list = field(default_factory=list)
    provider_allow_fallbacks: bool = True
    provider_force: Optional[str] = None
    # Stable per-conversation identifier forwarded to OpenRouter for
    # session-pinned routing/caching (keeps one conversation on the same
    # provider with a warm prompt cache).
    session_id: Optional[str] = None


@dataclass
class LLMResponse:
    """Result of a provider call."""

    text: str
    model: str
    usage: Optional[dict] = None
    cost_usd: Optional[float] = None


class LLMProvider(ABC):
    """Abstract LLM provider (sync — dhc's engine is thread-based).

    Providers set ``default_model`` at construction so callers can build
    per-call configs without knowing the resolved model.
    """

    default_model: str = "gpt-4o"

    @abstractmethod
    def generate(
        self, system: str, user: str, config: Optional[LLMConfig] = None
    ) -> LLMResponse:
        """Return the model's completion for *system* + *user*.

        Raises :class:`errors.TurnTimeoutError` when the call exceeds the
        configured timeout and :class:`errors.TurnError` on any other failure
        (after retries are exhausted).
        """

    @abstractmethod
    def close(self) -> None:
        """Release any underlying resources (connections, sessions, ...)."""


class OpenAIProvider(LLMProvider):
    """OpenAI-compatible provider wrapping the sync ``openai.OpenAI`` SDK.

    Defaults come from config: model ``deepseek/deepseek-v4-flash`` and
    base_url ``https://openrouter.ai/api/v1`` (the reference's default
    provider — OpenRouter). External OpenAI-compatible providers are enabled
    by passing a different ``base_url``. The API key is resolved by
    :func:`~dhc.config.merge_api_key` (``OPENROUTER_API_KEY`` →
    ``OPENAI_API_KEY``).

    OpenRouter routing: when ``base_url`` contains "openrouter", an
    ``extra_body`` is sent with ``provider_force`` / ``provider_ignore`` /
    ``provider_allow_fallbacks`` (only non-None/non-empty values) and
    ``session_id`` when provided.

    Retry policy: transient failures (``APITimeoutError``,
    ``APIConnectionError``, rate limits / HTTP 429, 5xx) are retried with
    exponential backoff + jitter, budgeted separately for generic transients
    (``max_retries``) and rate limits (``rate_limit_max_attempts``). On final
    failure the call raises :class:`errors.TurnError`. Timeout containment
    (INFO-020): the SDK client is constructed with ``timeout=timeout`` and
    every call is additionally bounded by a watchdog thread, so a hung
    provider raises :class:`errors.TurnTimeoutError` instead of hanging.
    """

    #: Exception types always classified as retryable (transient).
    _RETRYABLE_TYPES: tuple = (
        openai.APITimeoutError,
        openai.APIConnectionError,
        openai.RateLimitError,
        openai.InternalServerError,
    )

    #: Keywords that mark a message as a server/transient failure when the
    #: exception type is unknown (other providers).
    _RETRYABLE_KEYWORDS: tuple = (
        "rate_limit", "rate limit", "429", "too many requests",
        "server_error", "500", "502", "503", "504",
        "timeout", "timed out", "temporary", "connection", "network",
        "overloaded", "capacity",
    )

    #: Keywords that specifically mark a rate limit (budgeted separately).
    _RATE_LIMIT_KEYWORDS: tuple = (
        "rate_limit", "rate limit", "429", "too many requests",
        "engine_overloaded", "upstream_provider_shared_pool",
    )

    def __init__(
        self,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        verify_ssl: bool = True,
        provider_ignore: Optional[list] = None,
        provider_allow_fallbacks: bool = True,
        provider_force: Optional[str] = None,
        timeout: float = 500.0,
        max_retries: int = 4,
        rate_limit_max_attempts: int = 6,
        retry_base_delay_seconds: float = 1.0,
        retry_max_delay_seconds: float = 30.0,
        retry_jitter_seconds: float = 0.5,
        rate_limit_backoff_multiplier: float = 3.0,
        fallback_on_rate_limit: bool = True,
        price_input_per_mtok: Optional[float] = None,
        price_output_per_mtok: Optional[float] = None,
    ) -> None:
        settings = get_settings()
        provider_cfg = settings.provider
        self.default_model = model if model is not None else provider_cfg.model
        self._base_url = base_url if base_url is not None else provider_cfg.base_url
        self._api_key = api_key if api_key is not None else merge_api_key()
        self._verify_ssl = verify_ssl
        self._provider_ignore = list(provider_ignore or [])
        self._provider_allow_fallbacks = provider_allow_fallbacks
        self._provider_force = provider_force
        self.timeout = float(timeout)
        self.max_retries = max(int(max_retries), 0)
        self.rate_limit_max_attempts = max(int(rate_limit_max_attempts), 0)
        self.retry_base_delay_seconds = float(retry_base_delay_seconds)
        self.retry_max_delay_seconds = float(retry_max_delay_seconds)
        self.retry_jitter_seconds = float(retry_jitter_seconds)
        self.rate_limit_backoff_multiplier = float(rate_limit_backoff_multiplier)
        self.fallback_on_rate_limit = bool(fallback_on_rate_limit)
        self.price_input_per_mtok = price_input_per_mtok
        self.price_output_per_mtok = price_output_per_mtok
        # ``session_id`` is an OpenRouter-specific field; OpenAI's native API
        # rejects unknown body keys, so only forward routing to OpenRouter.
        self._is_openrouter = (
            self._base_url is not None and "openrouter" in self._base_url.lower()
        )
        # The openai client is constructed lazily on first use, so building a
        # provider never requires a key or touches the network.
        self._client = None

    # -- public API -----------------------------------------------------

    def available(self) -> bool:
        """True when an API key is configured (no network involved)."""
        return bool(self._api_key)

    def generate(
        self, system: str, user: str, config: Optional[LLMConfig] = None
    ) -> LLMResponse:
        cfg = config or LLMConfig(model=self.default_model)
        if not self._api_key:
            raise errors.TurnError("no API key configured")
        model = cfg.model or self.default_model
        kwargs: dict = {
            "model": model,
            "temperature": cfg.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        extra = self._build_extra_body(cfg)
        if extra:
            kwargs["extra_body"] = extra
        if cfg.max_tokens is not None:
            kwargs["max_tokens"] = cfg.max_tokens

        # Attempt budgets by failure class. A rate limit is NOT the same as a
        # generic transient error: shared upstream pool overloads routinely
        # outlast the seconds of backoff a plain timeout budget allows, so
        # counting per class means one kind of failure never consumes the
        # other's patience.
        attempts: dict = {False: 0, True: 0}
        last_error: Optional[Exception] = None
        worst_budget = max(1, self.max_retries, self.rate_limit_max_attempts)
        for _ in range(worst_budget):
            try:
                resp = self._call_with_timeout(
                    lambda: self._ensure_client().chat.completions.create(**kwargs)
                )
                return self._to_response(resp, model)
            except errors.TurnTimeoutError:
                # Watchdog fired: the call exceeded the budget. Never retry a
                # hang — surface it immediately (INFO-020).
                raise
            except Exception as exc:  # noqa: BLE001 - any LLM failure is a failed turn
                last_error = exc
                rate_limited = self._is_rate_limit(exc)
                attempts[rate_limited] += 1
                budget = (
                    self.rate_limit_max_attempts if rate_limited else self.max_retries
                )
                if not self._is_retryable(exc) or attempts[rate_limited] >= budget:
                    raise errors.TurnError(f"LLM call failed: {exc}") from exc
                # Adaptive backoff: exponential in the retry count for this
                # failure class, scaled up for rate limits, capped at the
                # configured ceiling, plus jitter.
                delay = self._delay_seconds(rate_limited, attempts[rate_limited])
                time.sleep(delay + random.uniform(0.0, self.retry_jitter_seconds))
        raise errors.TurnError(f"LLM call failed: {last_error}") from last_error

    def close(self) -> None:
        """Release the underlying openai client, if one was created."""
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()
            self._client = None

    # -- internals ------------------------------------------------------

    def _ensure_client(self):
        if self._client is None:
            if not self._api_key:
                raise errors.TurnError("no API key configured")
            self._client = openai.OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self.timeout,
                # The SDK transparently retries on timeout/connection errors up
                # to its own default (2) times, silently multiplying the
                # effective wait. dhc owns retries (INFO-020), so disable the
                # SDK's so the configured timeout is honored per attempt.
                max_retries=0,
            )
        return self._client

    def _build_extra_body(self, cfg: LLMConfig) -> Optional[dict]:
        """OpenRouter routing body; None when base_url is not OpenRouter or
        nothing is configured (only non-None/non-empty values are sent)."""
        if not self._is_openrouter:
            return None
        body: dict = {}
        force = cfg.provider_force or self._provider_force
        ignore = cfg.provider_ignore or self._provider_ignore
        if force:
            body["provider"] = {
                "order": [force],
                "allow_fallbacks": False,
                "ignore": ignore,
            }
        elif ignore:
            body["provider"] = {
                "ignore": ignore,
                "allow_fallbacks": (
                    cfg.provider_allow_fallbacks
                    if cfg.provider_ignore
                    else self._provider_allow_fallbacks
                ),
            }
        if cfg.session_id:
            body["session_id"] = cfg.session_id
        return body or None

    def _to_response(self, resp: object, model: str) -> LLMResponse:
        try:
            content = resp.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            raise errors.TurnError("LLM returned an empty completion") from exc
        if not content:
            raise errors.TurnError("LLM returned an empty completion")
        usage = self._extract_usage(getattr(resp, "usage", None))
        return LLMResponse(
            text=content,
            model=model,
            usage=usage,
            cost_usd=self._estimate_cost(usage),
        )

    @staticmethod
    def _extract_usage(usage: object) -> Optional[dict]:
        """Surface provider cost + prompt-cache info alongside raw token counts.

        The OpenAI-compatible usage object exposes ``prompt_tokens_details`` on
        providers that report it (OpenAI automatic caching, OpenRouter, ...)
        and, on OpenRouter, a ``cost`` field — the actual USD/credit cost of
        the request as billed.
        """
        if usage is None:
            return None
        out: dict = {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
        }
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached = getattr(details, "cached_tokens", None)
            if cached is not None:
                out["cached_tokens"] = int(cached)
        cost = getattr(usage, "cost", None)
        if cost is not None:
            out["cost"] = float(cost)
        return out

    def _estimate_cost(self, usage: Optional[dict]) -> Optional[float]:
        """USD estimate from token counts when per-1M-token prices are set."""
        if not usage or (
            self.price_input_per_mtok is None and self.price_output_per_mtok is None
        ):
            return None
        cost = 0.0
        if self.price_input_per_mtok is not None:
            cost += usage.get("prompt_tokens", 0) / 1_000_000 * self.price_input_per_mtok
        if self.price_output_per_mtok is not None:
            cost += (
                usage.get("completion_tokens", 0) / 1_000_000
                * self.price_output_per_mtok
            )
        return cost

    def _call_with_timeout(self, fn: Callable[[], object]) -> object:
        """Run *fn* bounded by ``timeout``; never hang (INFO-020)."""
        result: dict = {}

        def runner() -> None:
            try:
                result["value"] = fn()
            except BaseException as exc:  # noqa: BLE001 - re-raised in caller thread
                result["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(self.timeout)
        if thread.is_alive():
            raise errors.TurnTimeoutError(
                f"LLM call exceeded {self.timeout}s budget"
            )
        if "error" in result:
            raise result["error"]
        return result["value"]

    # -- retry classification / backoff ---------------------------------

    @classmethod
    def _is_rate_limit(cls, exc: Exception) -> bool:
        """True for HTTP 429 / explicit rate-limit failures, which get a longer
        retry budget than generic transient errors."""
        if isinstance(exc, openai.RateLimitError):
            return True
        if isinstance(exc, openai.APIStatusError):
            if getattr(exc, "status_code", None) == 429:
                return True
        error_str = str(exc).lower()
        return any(keyword in error_str for keyword in cls._RATE_LIMIT_KEYWORDS)

    @classmethod
    def _is_retryable(cls, exc: Exception) -> bool:
        """True for transient failures (timeouts, connection drops, rate
        limits, server errors) that are safe to retry."""
        for exc_type in cls._RETRYABLE_TYPES:
            if isinstance(exc, exc_type):
                return True
        if isinstance(exc, openai.APIStatusError):
            status = getattr(exc, "status_code", None)
            if status is not None and 500 <= status < 600:
                return True
        error_str = str(exc).lower()
        return any(keyword in error_str for keyword in cls._RETRYABLE_KEYWORDS)

    def _delay_seconds(self, rate_limited: bool, retry_count: int) -> float:
        """Backoff before the next retry: exponential in the retry count for
        this failure class, scaled up for rate limits, capped at the ceiling."""
        delay = self.retry_base_delay_seconds * (
            self.rate_limit_backoff_multiplier if rate_limited else 1.0
        ) * (2.0 ** (retry_count - 1))
        return min(delay, self.retry_max_delay_seconds)


class LLMClient:
    """Thin backward-compat wrapper around :class:`OpenAIProvider`.

    The provider (and its openai client) is constructed **lazily** on first
    use, so importing and constructing :class:`LLMClient` never requires an
    API key. Every call is bounded by ``timeout_seconds`` (INFO-020): a
    timeout raises :class:`errors.TurnTimeoutError`, any other failure raises
    :class:`errors.TurnError`.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        base_url: Optional[str] = None,
    ) -> None:
        settings = get_settings()
        provider_cfg = settings.provider
        self._provider = OpenAIProvider(
            model=model if model is not None else provider_cfg.model,
            base_url=base_url if base_url is not None else provider_cfg.base_url,
            api_key=api_key if api_key is not None else merge_api_key(),
            verify_ssl=provider_cfg.verify_ssl,
            provider_ignore=provider_cfg.provider_ignore,
            provider_allow_fallbacks=provider_cfg.provider_allow_fallbacks,
            provider_force=provider_cfg.provider_force,
            timeout=(
                timeout_seconds
                if timeout_seconds is not None
                else provider_cfg.call_timeout_seconds
            ),
            max_retries=provider_cfg.retry_max_attempts,
            rate_limit_max_attempts=provider_cfg.rate_limit_max_attempts,
            retry_base_delay_seconds=provider_cfg.retry_base_delay_seconds,
            retry_max_delay_seconds=provider_cfg.retry_max_delay_seconds,
            retry_jitter_seconds=provider_cfg.retry_jitter_seconds,
            rate_limit_backoff_multiplier=provider_cfg.rate_limit_backoff_multiplier,
            fallback_on_rate_limit=provider_cfg.fallback_on_rate_limit,
            price_input_per_mtok=provider_cfg.price_input_per_mtok,
            price_output_per_mtok=provider_cfg.price_output_per_mtok,
        )

    @property
    def _client(self) -> object:
        """The underlying openai client (test-injection slot, backward compat)."""
        return self._provider._client

    @_client.setter
    def _client(self, value: object) -> None:
        self._provider._client = value

    # -- public API -----------------------------------------------------

    def available(self) -> bool:
        """True when an API key is configured (no network involved)."""
        return self._provider.available()

    def generate_code_block(self, prompt: str, context: Optional[str] = None) -> str:
        """Return the next action's Python block for *prompt* (+ *context*).

        The model is instructed to return ONLY a single Python code block
        (INFO-002); any surrounding markdown fences are stripped.
        """
        user_content = (
            prompt if context is None else f"{prompt}\n\nContext:\n{context}"
        )
        response = self._provider.generate(_SYSTEM_PROMPT, user_content)
        return _strip_markdown_fences(response.text)

    def close(self) -> None:
        """Release the underlying openai client, if one was created."""
        self._provider.close()


class MockLLM:
    """Deterministic fake LLM for tests and demos (documented mock path).

    Two modes:

    * mapping: ``{prompt_substring: code_block}`` — the first key that is a
      substring of the prompt selects the block; otherwise *default* is used.
    * callable: ``fn(prompt, context) -> str`` — full control.

    Same interface as :class:`LLMClient`; never touches the network. Markdown
    fences are stripped from returned blocks, matching :class:`LLMClient`.
    """

    def __init__(
        self,
        mapping: Optional[Mapping[str, str]] = None,
        default: str = "",
        fn: Optional[Callable[[str, Optional[str]], str]] = None,
    ) -> None:
        self._mapping = dict(mapping or {})
        self._default = default
        self._fn = fn

    def available(self) -> bool:
        return True

    def generate_code_block(self, prompt: str, context: Optional[str] = None) -> str:
        if self._fn is not None:
            return _strip_markdown_fences(self._fn(prompt, context))
        for key, block in self._mapping.items():
            if key in prompt:
                return _strip_markdown_fences(block)
        return _strip_markdown_fences(self._default)

    def close(self) -> None:
        return None


@dataclass(frozen=True)
class RotReport:
    """Result of a context-rot check (INFO-021)."""

    rot: bool
    score: float
    signals: list


class ContextRotDetector:
    """Detects context rot on agent output streams (INFO-021).

    Heuristics (deterministic, documented):

    * ``repetition`` — ratio of repeated word trigrams to total trigrams.
    * ``degenerate_length`` — output shorter than ``min_length`` chars, or
      (when ``expected_length`` is set) less than half or more than double it.
    * ``repeated_failure_phrases`` — two or more failure phrases in the text.
    * ``low_novelty`` — Jaccard similarity to the most similar recent output
      in the rolling window (fed by :meth:`observe`).

    The overall score is the maximum sub-score; ``rot`` is true when the score
    reaches ``threshold``.
    """

    FAILURE_PHRASES = (
        "traceback",
        "error:",
        "exception",
        "i can't",
        "i cannot",
        "i'm unable",
        "failed",
        "sorry",
    )
    _SIGNAL_THRESHOLDS = {
        "repetition": 0.5,
        "degenerate_length": 0.5,
        "repeated_failure_phrases": 0.5,
        "low_novelty": 0.7,
    }

    def __init__(
        self,
        threshold: float = 0.6,
        window_size: int = 5,
        min_length: int = 20,
        expected_length: Optional[int] = None,
    ) -> None:
        self.threshold = threshold
        self.window_size = window_size
        self.min_length = min_length
        self.expected_length = expected_length
        self._window: deque = deque(maxlen=window_size)

    def detect(self, text: str) -> RotReport:
        """Score *text* without updating the rolling window."""
        scores = {
            "repetition": self._repetition_score(text),
            "degenerate_length": self._degenerate_score(text),
            "repeated_failure_phrases": self._failure_score(text),
            "low_novelty": self._novelty_score(text),
        }
        signals = [
            name
            for name, score in scores.items()
            if score >= self._SIGNAL_THRESHOLDS[name]
        ]
        score = max(scores.values()) if scores else 0.0
        return RotReport(
            rot=score >= self.threshold,
            score=round(score, 4),
            signals=signals,
        )

    def observe(self, text: str) -> RotReport:
        """Score *text*, then add it to the rolling window."""
        report = self.detect(text)
        self._window.append(text)
        return report

    # -- heuristics -----------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> list:
        return re.findall(r"[a-z0-9']+", text.lower())

    def _repetition_score(self, text: str) -> float:
        tokens = self._tokenize(text)
        if len(tokens) < 6:
            return 0.0
        n = 3
        grams = [tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)]
        if not grams:
            return 0.0
        repeated = len(grams) - len(set(grams))
        return repeated / len(grams)

    def _degenerate_score(self, text: str) -> float:
        if self.expected_length is None:
            return 1.0 if len(text) < self.min_length else 0.0
        ratio = len(text) / self.expected_length
        return 1.0 if ratio < 0.5 or ratio > 2.0 else 0.0

    def _failure_score(self, text: str) -> float:
        lowered = text.lower()
        count = sum(lowered.count(phrase) for phrase in self.FAILURE_PHRASES)
        if count < 2:
            return 0.0
        return min(1.0, count / 4.0)

    def _novelty_score(self, text: str) -> float:
        if not self._window:
            return 0.0
        tokens = set(self._tokenize(text))
        if not tokens:
            return 0.0
        best = 0.0
        for previous in self._window:
            prev_tokens = set(self._tokenize(previous))
            if not prev_tokens:
                continue
            best = max(best, len(tokens & prev_tokens) / len(tokens | prev_tokens))
        return best