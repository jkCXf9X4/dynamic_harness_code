"""Structured prompt composition for dhc agents (SUPERSEDED by G-02).

Historical note: this module was authored as the "presetup prompts" pattern
(a static system prompt file plus role/orchestrator constants and a steerage
block, composed once at agent start). It was never wired into the driver:
``LLMDriver`` assembled its prompt from its own template, and an earlier
revision of this docstring falsely claimed the driver consumed
:func:`compose_initial_prompt`.

G-02 resolved that split by making prompt assembly a workspace-swappable kit
citizen: the default is :func:`dhc.llm.driver.default_build_prompt` (the
byte-identical extraction of the historical ``LLMDriver._build_prompt``),
installed in every agent workspace as ``build_prompt``. An agent that
replaces it — the workspace name or the persistent ``state["build_prompt"]``
slot — changes the prompt the LLM receives.

This module is therefore explicitly SUPERSEDED by that citizen. It is kept
(unwired) as a standalone composition utility for callers that want the
structured system-prompt/steerage layout; nothing in the runtime consumes
it. This repo has no ``deprecated/`` convention, so the supersession is
recorded here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

#: The role value that promotes an agent to the delegation-only orchestrator.
ORCHESTRATOR_ROLE = "orchestrator"

#: Static system prompt loaded from the package data file. Falls back to an
#: inline constant if the file is missing (e.g. zipped installs).
_AGENT_SYSTEM_PROMPT_FALLBACK = """# Dynamic Harness Code (dhc)

## Lifecycle

**ANALYZE → DECOMPOSE → DELEGATE → VERIFY → SYNTHESIZE → CONSOLIDATE & CLEAN**

The lifecycle is iterative. If verification shows the readiness criterion is unmet, re-plan and continue. Never force a failed plan to completion.

## Coded-Action Loop

One turn = one Python block. Respond with ONLY a single Python code block — the next action — executed against your per-agent persistent REPL, so state persists between turns. No prose, no explanation, no markdown outside the code block. End the block by calling complete(...) when the requirement is satisfied, or fail(reason) when it cannot be. Each turn follows analyze → implement → verify → report; if it cannot be verified, it is not done.
"""


def _load_agent_system_prompt() -> str:
    """Load the static system prompt from the package data file."""
    path = Path(__file__).parent / "agent_system_prompt.txt"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return _AGENT_SYSTEM_PROMPT_FALLBACK


AGENT_SYSTEM_PROMPT = _load_agent_system_prompt()

def build_system_prompt(base: str = AGENT_SYSTEM_PROMPT, role: Optional[str] = None) -> str:
    """Compose the effective system prompt for an agent (thin role overlay).

    A role gets a scope tag prepended; with no role set, no role tag is
    emitted. (The historical ``ORCHESTRATOR_SYSTEM_PROMPT`` delegation-only
    directive was removed in W1.5 — it taught callables that do not exist
    in the agent namespace; the doctrine prompt plus the registry-generated
    API section is the single prompt now.)
    """
    parts: list[str] = []
    if role:
        parts.append(
            f"You are scoped to the role: {role}. Stay in bounds — operate only within this role's scope."
        )
    parts.append(base.rstrip())
    return "\n\n".join(parts)


def build_steerage(
    intent: Optional[str] = None,
    end_state: Optional[str] = None,
    constraints: Optional[Sequence[str]] = None,
    authority: Optional[str] = None,
    focus: Optional[str] = None,
    budget: Optional[str] = None,
    environment: Optional[str] = None,
) -> str:
    """Render the static, cache-friendly steerage block (mission brief, focus,
    budget/timeout guidance, environment info).

    Folded into the system prompt ONCE at agent start — NOT a per-turn
    observation. Only non-empty sections are emitted, so the composed prefix
    stays byte-identical for prompt caching.
    """
    parts: list[str] = []
    if intent:
        parts.append(f"[INTENT] {intent}")
    if end_state:
        parts.append(f"[END STATE] {end_state}")
    if constraints:
        bullets = "\n".join(f"- {c}" for c in constraints)
        parts.append(f"[CONSTRAINTS]\n{bullets}")
    if authority:
        parts.append(f"[AUTHORITY] {authority}")
    if focus:
        parts.append(f"[FOCUS] {focus}")
    if budget:
        parts.append(f"[BUDGET] {budget}")
    if environment:
        parts.append(f"[ENVIRONMENT]\n{environment}")
    return "\n".join(parts)


def build_user_message(requirement: str, role: Optional[str] = None) -> str:
    """The initial user message seeding the conversation (task plus optional
    role scope)."""
    if role:
        return f"[ROLE] {role}\n\n[TASK] {requirement}"
    return requirement


