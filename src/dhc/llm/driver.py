"""The pluggable brain: turns a requirement into coded actions.

One turn = one Python block (INFO-002). The driver is the runtime's
requirement-to-code generator: given the agent, it returns the next action
block, or ``None`` when the agent should settle.

Two drivers are provided:

* :class:`LLMDriver` — the real path: builds a prompt from the agent's
  requirement / acceptance / status / recent events and asks an LLM client
  (``client.generate_code_block(prompt, context) -> str``) for the next
  block. Resilient per INFO-020: a client failure returns a block that calls
  ``fail(reason)`` so the turn settles failed rather than hanging; an empty
  block or the turn cap settles the agent.
* :class:`MockDriver` — the deterministic mock path for tests and demos: a
  scripted list of code blocks returned in order, then ``None``.

:func:`driver_from_settings` is the factory: mock mode (or no API key) yields
a :class:`MockDriver` with a sensible default script; otherwise an
:class:`LLMDriver` over a real :class:`~dhc.llm.LLMClient` wrapping an
:class:`~dhc.llm.OpenAIProvider` (model / base_url / timeout from
``settings.provider``; API key via ``merge_api_key()`` —
``OPENROUTER_API_KEY`` → ``OPENAI_API_KEY``).
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Optional

from ..data.config import get_settings, merge_api_key
from .llm import LLMClient

logger = logging.getLogger(__name__)

#: The in-code surface action blocks may call (documented in the prompt).
_SURFACE_DOC = (
    "Available in the namespace: agent, publish(headline, summary, report), "
    "spawn(requirement, acceptance=(), driver=None, on_done=None), "
    "complete(headline, artifacts=()), fail(reason), cancel(reason), "
    "status(), result(), tool(callable, *args), bash(cmd), room(name), "
    "await_(handle), poll(handle), children_of(handle), "
    "messenger.send(recipient_id, body), escalate(reason), "
    "ask_operator(question)."
)

#: The default mock script: publish one artifact, then complete.
DEFAULT_SCRIPT: list[str] = [
    "art = publish('hello', 'summary', 'report body')\n"
    "result = complete('done', artifacts=[art.id])\n"
]


class LLMDriver:
    """The real driver: an LLM client turns the requirement into code blocks.

    Constructor
    -----------
    - ``client`` — anything with ``generate_code_block(prompt, context) -> str``
      (the committed :class:`~dhc.llm.LLMClient` or :class:`~dhc.llm.MockLLM`).
    - ``system_prompt`` — optional extra system guidance prepended to the
      prompt.
    - ``max_turns`` — the turn cap; after this many driver calls the agent is
      told to settle (``None``).
    - ``rot_detector`` — optional :class:`~dhc.llm.ContextRotDetector`; each
      generated block is scored and a warning is logged on rot (INFO-021).

    ``__call__(agent) -> str | None`` returns the next code block, or ``None``
    when the agent should settle. Resilient (INFO-020): a client failure
    returns a block that calls ``fail(reason)`` so the turn settles failed
    rather than hanging; the next call settles.
    """

    def __init__(
        self,
        client: Any,
        system_prompt: Optional[str] = None,
        max_turns: int = 20,
        rot_detector: Optional[Any] = None,
    ) -> None:
        self._client = client
        self._system_prompt = system_prompt
        self._max_turns = max_turns
        self._rot_detector = rot_detector
        self._turns = 0
        self._failed_once = False

    def __call__(self, agent: Any) -> Optional[str]:
        if self._turns >= self._max_turns:
            return None
        if self._failed_once:
            # A previous client failure already produced a fail() turn; settle
            # now so the agent settles failed instead of looping.
            return None
        self._turns += 1
        prompt = self._build_prompt(agent)
        context = self._recent_context(agent)
        try:
            code = self._client.generate_code_block(prompt, context)
        except Exception as exc:  # noqa: BLE001 - any client failure is contained
            self._failed_once = True
            reason = f"LLM call failed: {type(exc).__name__}: {exc}"
            logger.warning("LLMDriver client failure for agent %s: %s", agent.id, reason)
            return f"fail({json.dumps(reason)})"
        if not code or not code.strip():
            return None
        if self._rot_detector is not None:
            report = self._rot_detector.observe(code)
            if report.rot:
                logger.warning(
                    "context rot detected for agent %s (score=%.3f, signals=%s)",
                    agent.id,
                    report.score,
                    report.signals,
                )
        return code

    # -- prompt construction ------------------------------------------------

    def _build_prompt(self, agent: Any) -> str:
        parts: list[str] = []
        if self._system_prompt:
            parts.append(self._system_prompt)
        parts.append(
            "You are the action generator for a recursive agent runtime. "
            "Write ONE Python block — the next action — that makes progress "
            "on the agent's requirement. The block runs against the agent's "
            "persistent REPL, so state persists between turns. End the block "
            "by calling complete(...) when the requirement is satisfied, or "
            "fail(reason) when it cannot be. Respond with ONLY the Python "
            "code, no prose."
        )
        parts.append(_SURFACE_DOC)
        parts.append(f"Requirement: {agent.requirement}")
        if agent.acceptance:
            parts.append(f"Acceptance criteria: {list(agent.acceptance)}")
        status = agent.status()
        parts.append(
            f"Current status: done={status.done} ok={status.ok} "
            f"reason={status.reason!r}"
        )
        context = self._recent_context(agent)
        if context:
            parts.append(f"Recent events:\n{context}")
        return "\n\n".join(parts)

    @staticmethod
    def _recent_context(agent: Any, limit: int = 5) -> str:
        """Return a short summary of the agent's recent event stream, if any.

        The runtime owns the stream surface (INFO-051); the driver is part of
        the runtime machinery, so draining the agent's own events here is
        legitimate — the boundary log has already persisted them.
        """
        runtime = getattr(agent, "_runtime", None)
        if runtime is None:
            return ""
        try:
            events = runtime.events(agent.id)
        except Exception:  # noqa: BLE001 - context is best-effort
            return ""
        if not events:
            return ""
        lines = []
        for event in events[-limit:]:
            payload = json.dumps(event.payload, default=str)[:200]
            lines.append(f"- {event.kind.value}: {payload}")
        return "\n".join(lines)


class MockDriver:
    """Deterministic driver for tests and demos.

    ``script`` is a list of code blocks; they are returned in order, then
    ``None`` (settle). :meth:`single` builds a one-block driver.
    """

    def __init__(self, script: list[str]) -> None:
        self._script = list(script)
        self._calls = 0

    def __call__(self, agent: Any) -> Optional[str]:
        del agent  # scripted: the agent does not influence the script
        if self._calls >= len(self._script):
            return None
        code = self._script[self._calls]
        self._calls += 1
        return code

    @classmethod
    def single(cls, code: str) -> "MockDriver":
        """Build a one-block driver."""
        return cls([code])


def driver_from_settings(settings: Any = None, mock: bool = False) -> Any:
    """Factory: pick the driver for *settings*.

    ``mock=True`` or no API key -> a :class:`MockDriver` with the default
    script; otherwise an :class:`LLMDriver` over a real
    :class:`~dhc.llm.LLMClient` wrapping an
    :class:`~dhc.llm.OpenAIProvider` (constructed lazily — no network at
    build time). The key is resolved by :func:`~dhc.config.merge_api_key`
    (``OPENROUTER_API_KEY`` → ``OPENAI_API_KEY``); model / base_url / timeout
    come from ``settings.provider``.
    """
    if settings is None:
        settings = get_settings()
    has_key = bool(merge_api_key())
    if mock or not has_key:
        return MockDriver(list(DEFAULT_SCRIPT))
    provider_cfg = settings.provider
    client = LLMClient(
        api_key=merge_api_key(),
        model=provider_cfg.model,
        timeout_seconds=provider_cfg.call_timeout_seconds,
        base_url=provider_cfg.base_url,
    )
    return LLMDriver(client)