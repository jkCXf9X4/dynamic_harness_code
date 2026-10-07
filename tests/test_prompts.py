"""Tests for dhc.prompts — static system prompt, role constants, steerage.

Verifies the "presetup" pattern: the composed prompt is deterministic
(byte-identical for prompt caching) and the steerage block is folded into the
system prompt once at agent start, not a per-turn observation.
"""

from __future__ import annotations

from dhc.prompts import (
    AGENT_SYSTEM_PROMPT,
    ORCHESTRATOR_ROLE,
    ORCHESTRATOR_SYSTEM_PROMPT,
    build_steerage,
    build_system_prompt,
    build_user_message,
    compose_initial_prompt,
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


def test_build_system_prompt_prepends_orchestrator_only_for_orchestrator_role():
    base = "BASE PROMPT"
    plain = build_system_prompt(base, role=None)
    assert plain == "BASE PROMPT"
    assert ORCHESTRATOR_SYSTEM_PROMPT not in plain

    scoped = build_system_prompt(base, role="security-auditor")
    assert "security-auditor" in scoped
    assert ORCHESTRATOR_SYSTEM_PROMPT not in scoped

    orch = build_system_prompt(base, role=ORCHESTRATOR_ROLE)
    assert orch.startswith(ORCHESTRATOR_SYSTEM_PROMPT)
    assert "BASE PROMPT" in orch


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


def test_compose_initial_prompt_contains_requirement_and_steerage():
    composed = compose_initial_prompt(
        "Build the widget",
        role=ORCHESTRATOR_ROLE,
        intent="Adopt presetup pattern",
        end_state="Tests green",
        constraints=["No new deps"],
        authority="Adjust signatures",
        focus="Prompts",
        budget="7200s",
        environment="Python 3.10",
    )
    assert "Build the widget" in composed
    assert "[INTENT] Adopt presetup pattern" in composed
    assert "[END STATE] Tests green" in composed
    assert "- No new deps" in composed
    assert "[AUTHORITY] Adjust signatures" in composed
    assert "[FOCUS] Prompts" in composed
    assert "[BUDGET] 7200s" in composed
    assert "[ENVIRONMENT]" in composed
    assert ORCHESTRATOR_SYSTEM_PROMPT in composed
    assert AGENT_SYSTEM_PROMPT.rstrip() in composed


def test_compose_initial_prompt_is_deterministic_byte_identical():
    kwargs = dict(
        requirement="Build the widget",
        role=ORCHESTRATOR_ROLE,
        intent="Adopt presetup pattern",
        end_state="Tests green",
        constraints=["No new deps", "Python 3.10"],
        authority="Adjust signatures",
        focus="Prompts",
        budget="7200s",
        environment="Python 3.10.12",
    )
    first = compose_initial_prompt(**kwargs)
    second = compose_initial_prompt(**kwargs)
    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")


def test_build_user_message_includes_role_and_requirement():
    assert build_user_message("Do the thing") == "Do the thing"
    msg = build_user_message("Do the thing", role="auditor")
    assert "[ROLE] auditor" in msg
    assert "[TASK] Do the thing" in msg