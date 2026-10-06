"""LLM integration for dhc — real client, mock path, context-rot detection.

INFO-020 (timeout containment): every LLM call is bounded by
``timeout_seconds``. A timed-out call raises :class:`errors.TurnTimeoutError`
and any other failure raises :class:`errors.TurnError`, so the runtime can
surface a failed turn without hanging or crashing the agent.

INFO-021 (context-rot detection): :class:`ContextRotDetector` scores an agent
output stream for degradation signatures — n-gram repetition, degenerate
length, repeated failure phrases, and low novelty against a rolling window of
recent outputs.

Mock path (documented): :class:`MockLLM` is a deterministic fake with the same
interface as :class:`LLMClient`. Use it in tests and demos instead of the real
client::

    mock = MockLLM({"def action": "def action():\\n    return 1"})
    code = mock.generate_code_block("please write def action")
"""

from __future__ import annotations

import re
import threading
from collections import deque
from dataclasses import dataclass
from typing import Callable, Mapping, Optional

import openai

from . import errors
from .config import get_settings

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


class LLMClient:
    """Thin wrapper around the openai chat-completions client.

    The openai client is constructed **lazily** on first use, so importing and
    constructing :class:`LLMClient` never requires an API key. Every call is
    bounded by ``timeout_seconds`` (INFO-020): a timeout raises
    :class:`errors.TurnTimeoutError`, any other failure raises
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
        self._api_key = api_key if api_key is not None else settings.openai_api_key
        self._model = model if model is not None else settings.openai_model
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else settings.llm_timeout_seconds
        )
        self._base_url = base_url
        self._client = None

    # -- public API -----------------------------------------------------

    def available(self) -> bool:
        """True when an API key is configured (no network involved)."""
        return bool(self._api_key)

    def generate_code_block(self, prompt: str, context: Optional[str] = None) -> str:
        """Return the next action's Python block for *prompt* (+ *context*).

        The model is instructed to return ONLY a single Python code block
        (INFO-002); any surrounding markdown fences are stripped.
        """
        client = self._ensure_client()
        user_content = (
            prompt if context is None else f"{prompt}\n\nContext:\n{context}"
        )
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ]
        try:
            response = self._call_with_timeout(
                lambda: client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    temperature=0.0,
                )
            )
        except openai.APITimeoutError as exc:
            raise errors.TurnTimeoutError(
                f"LLM call timed out after {self._timeout_seconds}s"
            ) from exc
        except errors.TurnTimeoutError:
            raise
        except Exception as exc:  # noqa: BLE001 - any LLM failure is a failed turn
            raise errors.TurnError(f"LLM call failed: {exc}") from exc
        try:
            content = response.choices[0].message.content
        except (AttributeError, IndexError) as exc:
            raise errors.TurnError("LLM returned an empty completion") from exc
        if not content:
            raise errors.TurnError("LLM returned an empty completion")
        return _strip_markdown_fences(content)

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
            if not self.available():
                raise errors.TurnError("no OpenAI API key configured")
            self._client = openai.OpenAI(
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            )
        return self._client

    def _call_with_timeout(self, fn: Callable[[], object]) -> object:
        """Run *fn* bounded by ``timeout_seconds``; never hang (INFO-020)."""
        result: dict = {}

        def runner() -> None:
            try:
                result["value"] = fn()
            except BaseException as exc:  # noqa: BLE001 - re-raised in caller thread
                result["error"] = exc

        thread = threading.Thread(target=runner, daemon=True)
        thread.start()
        thread.join(self._timeout_seconds)
        if thread.is_alive():
            raise errors.TurnTimeoutError(
                f"LLM call exceeded {self._timeout_seconds}s budget"
            )
        if "error" in result:
            raise result["error"]
        return result["value"]


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