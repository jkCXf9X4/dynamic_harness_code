"""Tests for dhc.prompts — static system prompt, role constants, steerage.

Verifies the "presetup" pattern: the composed prompt is deterministic
(byte-identical for prompt caching) and the steerage block is folded into the
system prompt once at agent start, not a per-turn observation.
"""

from __future__ import annotations

from dhc.llm.prompts import (
    AGENT_SYSTEM_PROMPT,
    ORCHESTRATOR_ROLE,
    build_steerage,
    build_system_prompt,
    build_user_message,
)


def test_agent_system_prompt_loads_from_file_and_has_key_phrases():
    # Loaded from the package data file (not the inline fallback).
    assert "Coded-Action Loop" in AGENT_SYSTEM_PROMPT
    assert "ANALYZE → DECOMPOSE → DELEGATE → VERIFY → SYNTHESIZE → CONSOLIDATE & CLEAN" in AGENT_SYSTEM_PROMPT
    assert "persistent REPL" in AGENT_SYSTEM_PROMPT
    assert "analyze → implement → verify → report" in AGENT_SYSTEM_PROMPT
    assert "Authority to adapt within the intent" in AGENT_SYSTEM_PROMPT
    assert "headline → summary → report" in AGENT_SYSTEM_PROMPT
    assert "canonical" in AGENT_SYSTEM_PROMPT.lower()
    assert "context hygiene" in AGENT_SYSTEM_PROMPT.lower()


def test_build_system_prompt_is_a_thin_role_overlay():
    """W1.5: the orchestrator directive is gone (it taught callables that
    do not exist in the agent namespace); any role gets a scope tag and
    the base is appended unchanged."""
    base = "BASE PROMPT"
    plain = build_system_prompt(base, role=None)
    assert plain == "BASE PROMPT"

    scoped = build_system_prompt(base, role="security-auditor")
    assert "security-auditor" in scoped
    assert "BASE PROMPT" in scoped

    # The historical delegation-only directive must not resurface.
    assert "ORCHESTRATOR" not in scoped
    assert "delegate" not in scoped.lower() or "delegat" not in scoped.lower()


def test_build_system_prompt_orchestrator_role_is_just_a_scope_tag():
    """role=ORCHESTRATOR_ROLE is now an ordinary scope tag (W1.5)."""
    orch = build_system_prompt("BASE PROMPT", role=ORCHESTRATOR_ROLE)
    assert "BASE PROMPT" in orch
    assert ORCHESTRATOR_ROLE in orch


def test_build_steerage_includes_provided_blocks_and_omits_none():
    steerage = build_steerage(
        intent="Why this matters",
        end_state="Done looks like",
        constraints=["No network", "Python 3.10"],
        authority="Adapt within intent",
        focus="Prompts engineer",
        budget="7200s wall clock",
        environment="Python 3.10.12",
    )
    assert "[INTENT] Why this matters" in steerage
    assert "[END STATE] Done looks like" in steerage
    assert "[CONSTRAINTS]" in steerage
    assert "- No network" in steerage
    assert "- Python 3.10" in steerage
    assert "[AUTHORITY] Adapt within intent" in steerage
    assert "[FOCUS] Prompts engineer" in steerage
    assert "[BUDGET] 7200s wall clock" in steerage
    assert "[ENVIRONMENT]" in steerage
    assert "Python 3.10.12" in steerage

    empty = build_steerage()
    assert empty == ""
    partial = build_steerage(intent="only intent")
    assert "[INTENT] only intent" in partial
    assert "[END STATE]" not in partial
    assert "[CONSTRAINTS]" not in partial
    assert "[AUTHORITY]" not in partial
    assert "[FOCUS]" not in partial
    assert "[BUDGET]" not in partial
    assert "[ENVIRONMENT]" not in partial


def test_agent_system_prompt_has_no_drifted_callable_teachings():
    """W1.5: the doctrine prompt teaches no callable that is not in the
    agent surface (the conformance test cross-checks the wired namespace;
    this pins the key drift the rewrite removed)."""
    for drifted in ("converse(", "report()", "plan(steps", "`prune`", "`compress`"):
        assert drifted not in AGENT_SYSTEM_PROMPT, drifted
    # escalate takes TWO args now.
    assert "escalate(reason)" not in AGENT_SYSTEM_PROMPT


def test_build_user_message_includes_role_and_requirement():
    assert build_user_message("Do the thing") == "Do the thing"
    msg = build_user_message("Do the thing", role="auditor")
    assert "[ROLE] auditor" in msg
    assert "[TASK] Do the thing" in msg