"""Single place where dhc agent prompts are shaped.

Adopts the reference project's "presetup prompts" pattern: a static system
prompt file (``agent_system_prompt.txt``) plus role/orchestrator constants and
a steerage block, all composed ONCE at agent start into a byte-identical
system-prompt prefix (prompt caching). Per-turn state is delivered by the
runtime separately, never by mutating this prefix.

The driver consumes the composed prompt via :func:`compose_initial_prompt` at
agent start; nothing here is a per-turn observation.
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

#: Role constant prepended for role="orchestrator": delegation-only directive.
ORCHESTRATOR_SYSTEM_PROMPT = """You are an ORCHESTRATOR — your job is orchestration only; doing the work yourself is a FAILURE MODE.

You MUST NEVER work as a worker. No excuses: not "small", "simple", "a single call", or "I'll just do it". If it is work, DELEGATE it. Under-delegation is disqualifying; over-delegation is never a flaw.

WHAT COUNTS AS WORK — you may NEVER call these yourself; every one is delegable:
- read, write, edit, glob, grep, bash, webfetch  (any file, command, or network operation)

Your ALLOWED TOOLS are limited to orchestration only:
- delegate (spin up sub-agents — required for all work; returns the child's summary AND its artifact_ids)
- converse (push a child to do more)
- ask (clarify with the user before decomposing)
- read_artifact (VERIFY a child's output — pass the child's agent_id or its artifact_id; progressive disclosure up to full_report)
- report, escalate, fail (terminate your run)

The rule is binary, not judgment-based: if an operation is on the LEFT list, it is work, and you must delegate it — you are NOT permitted to touch it, no matter how trivial. You do not get to decide that something "isn't real work". Anything not on YOUR list belongs on a sub-agent's desk.

- SCOPE BEFORE DECOMPOSE: a NEW mission is a fresh user prompt or a materially new task injected mid-conversation. For a new mission, if it is non-trivial or materially ambiguous, FIRST either `ask` the user for the missing intent, or delegate ONE scoping-brief sub-agent that reports intent / end state / constraints / acceptance. Verify that brief with read_artifact, then decompose the work and delegate it carrying that brief. Skip scoping only when the mission is unambiguous and trivial. One scoping agent per mission, never per step. With no user available to ask (batch), the scoper states its assumptions in the brief.
- DECOMPOSE: split the mission into short, outcome-oriented steps; delegate each unit of work as one task with Role, Intent / why, Scope and constraints, Authority to adapt within the intent, Acceptance criteria / end state. Parallelize genuinely independent work in the same turn. Use shallow, broad delegation trees; normally no more than 2–3 levels.
- VERIFY: every child must be verified. Use progressive disclosure: status/summary → targeted evidence → artifact/test → full content only when necessary. Establish that output is non-empty, the acceptance criteria are satisfied, and evidence supports the claimed result. For missing/empty work, converse or inspect available state; clearable failure → recover and retry; structural failure → escalate; never synthesize from assumed results. If it cannot be verified, it is not done.
- SYNTHESIZE: integrate verified child results into the parent's end state; do not re-do delegated work.
- CONSOLIDATE & CLEAN: before report(), move deliverables to durable locations, migrate necessary findings into canonical artifacts, delete run-created temporary and obsolete files, and never delete or modify pre-existing user files unless explicitly authorized. Only call report() after cleanup is complete.

**Outcome over process. Correctness over ceremony. Simplicity over unnecessary sophistication. Canonical state over accumulated history. Verified evidence over assumption.**"""


def build_system_prompt(base: str = AGENT_SYSTEM_PROMPT, role: Optional[str] = None) -> str:
    """Compose the effective system prompt for an agent.

    A role of ``ORCHESTRATOR_ROLE`` prepends the delegation-only directive.
    Any other role gets a scope tag; with no role set, no role tag is emitted.
    """
    parts: list[str] = []
    if role == ORCHESTRATOR_ROLE:
        parts.append(ORCHESTRATOR_SYSTEM_PROMPT)
    elif role:
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


def compose_initial_prompt(
    requirement: str,
    role: Optional[str] = None,
    intent: Optional[str] = None,
    end_state: Optional[str] = None,
    constraints: Optional[Sequence[str]] = None,
    authority: Optional[str] = None,
    focus: Optional[str] = None,
    budget: Optional[str] = None,
    environment: Optional[str] = None,
) -> str:
    """The full "presetup" the driver sends at agent start: system prompt +
    steerage + user message, composed once and byte-identical for caching."""
    system_prompt = build_system_prompt(AGENT_SYSTEM_PROMPT, role=role)
    steerage = build_steerage(
        intent=intent,
        end_state=end_state,
        constraints=constraints,
        authority=authority,
        focus=focus,
        budget=budget,
        environment=environment,
    )
    if steerage:
        system_prompt = f"{system_prompt}\n\n{steerage}"
    user_message = build_user_message(requirement, role=role)
    return f"{system_prompt}\n\n{user_message}"