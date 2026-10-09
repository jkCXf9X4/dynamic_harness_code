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


def _workspace_context(runtime: Any, agent_id: str) -> Optional[Any]:
    """Return the agent's fabrication context (the kit's ``state`` holder).

    Best-effort: the context is the workspace ``context`` citizen (a
    :class:`~dhc.llm.fabrication.FabricationContext`); anything else (no
    workspace yet, a broken/deleted context) returns ``None``. The driver
    uses it to reach the persistent ``state`` dict — the same seam
    ``state["_driver"]`` lives in — without importing the kit.
    """
    engine = getattr(runtime, "repl_engine", None)
    if engine is None:
        return None
    try:
        ctx = engine.globals_for(agent_id).get("context")
    except Exception:  # noqa: BLE001 - lookup is best-effort
        return None
    if ctx is None or not hasattr(ctx, "state"):
        return None
    return ctx


#: The default prompt assembly (G-02): the byte-identical extraction of
#: the historical ``LLMDriver._build_prompt`` template. The kit installs this
#: as the ``build_prompt`` workspace citizen; an agent that replaces it
#: changes the prompt the LLM receives (the driver resolves the override
#: through the same workspace-state seam as ``state["_driver"]``).
def default_build_prompt(
    agent: Any,
    system_prompt: Optional[str] = None,
    recent_context: str = "",
) -> str:
    """Assemble the default prompt for *agent* (byte-identical to the
    historical ``LLMDriver._build_prompt``).

    *system_prompt* is the driver's optional extra guidance (prepended when
    set); *recent_context* is the pre-rendered recent-events block (appended
    when non-empty). The golden tests in ``tests/llm/test_prompt_assembly.py``
    pin the exact bytes.
    """
    parts: list[str] = []
    if system_prompt:
        parts.append(system_prompt)
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
    if recent_context:
        parts.append(f"Recent events:\n{recent_context}")
    return "\n\n".join(parts)


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

    Prompt assembly is workspace-swappable (G-02): ``_build_prompt`` first
    looks for a ``build_prompt`` override in the agent's workspace (the
    workspace name, or the persistent ``state["build_prompt"]`` slot — the
    same seam ``state["_driver"]`` uses), and falls back to the byte-identical
    :func:`default_build_prompt` when there is none.
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
            # G-06: stash the latest report on the agent — a
            # runtime-machinery rendezvous (like ``agent._last_result``)
            # the pump's between-step rot tripwire reads. Observe-only:
            # the block is still returned unchanged.
            try:
                agent._last_rot_report = report
            except Exception:  # noqa: BLE001 - best-effort rendezvous
                pass
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
        """Assemble the prompt, honoring a workspace ``build_prompt`` override.

        Resolution order (G-02): (1) a ``build_prompt`` name in the agent's
        workspace (the kit installs the default there; an agent that replaces
        it from workspace code wins), (2) the persistent
        ``state["build_prompt"]`` slot (the same seam ``state["_driver"]``
        uses — it survives the per-turn namespace refresh), (3) the
        byte-identical :func:`default_build_prompt`.

        An override is called as ``build_prompt(agent, driver)`` — the driver
        is passed so a custom assembly can reuse its helpers (e.g.
        ``driver._recent_context``) — and must return the prompt string.
        """
        override = self._resolve_build_prompt(agent)
        if override is not None:
            return override(agent, self)
        return default_build_prompt(
            agent,
            system_prompt=self._system_prompt,
            recent_context=self._recent_context(agent),
        )

    def _resolve_build_prompt(self, agent: Any) -> Optional[Callable[[Any, Any], str]]:
        """Find a workspace ``build_prompt`` override, if any.

        Resolution order (G-02): (1) the workspace name — the kit installs
        the default there, and an agent that replaces it from workspace code
        wins until the next per-turn namespace refresh; (2) the persistent
        ``state["build_prompt"]`` slot — the same seam as
        ``state["_driver"]``, reached through the agent's fabrication
        context, which survives the refresh. The default itself is never an
        override. Lookups are best-effort: a missing workspace, a missing
        context, or a non-callable value falls through to the default.
        """
        runtime = getattr(agent, "_runtime", None)
        if runtime is None:
            return None
        # (1) The workspace name.
        engine = getattr(runtime, "repl_engine", None)
        if engine is not None:
            try:
                ws = engine.globals_for(agent.id)
            except Exception:  # noqa: BLE001 - lookup is best-effort
                ws = None
            if ws:
                fn = ws.get("build_prompt")
                if callable(fn) and fn is not default_build_prompt:
                    return fn
        # (2) The persistent state slot (survives the namespace refresh).
        ctx = _workspace_context(runtime, agent.id)
        if ctx is not None:
            fn = ctx.state.get("build_prompt")
            if callable(fn) and fn is not default_build_prompt:
                return fn
        return None

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


def driver_from_settings(
    settings: Any = None,
    mock: bool = False,
    rot_detector: Optional[Any] = None,
) -> Any:
    """Factory: pick the driver for *settings*.

    ``mock=True`` or no API key -> a :class:`MockDriver` with the default
    script; otherwise an :class:`LLMDriver` over a real
    :class:`~dhc.llm.LLMClient` wrapping an
    :class:`~dhc.llm.OpenAIProvider` (constructed lazily — no network at
    build time). The key is resolved by :func:`~dhc.config.merge_api_key`
    (``OPENROUTER_API_KEY`` → ``OPENAI_API_KEY``); model / base_url / timeout
    come from ``settings.provider``.

    ``rot_detector`` — optional :class:`~dhc.llm.ContextRotDetector`; when
    wired, each generated block is scored and a warning is logged on rot
    (INFO-021). Observe-only: it never prunes.
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
    return LLMDriver(client, rot_detector=rot_detector)