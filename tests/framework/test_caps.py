"""W5.2: the single alias table + ConfigResolver (caps.py).

The 11 ad-hoc ``_BUDGET_CAP_KEYS`` aliases collapse to one explicit
:data:`~dhc.framework.caps.ALIASES` table with a :class:`DeprecationWarning`
on alias use, and cap ceilings resolve through one
:class:`~dhc.framework.caps.ConfigResolver` (W5.1).
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from dhc.data.config import HarnessConfig, SafetyConfig, Settings
from dhc.framework.caps import (
    ALIASES,
    CAP_NAMES,
    ConfigResolver,
    agent_budgets,
    cap_limit,
    read_cap,
    resolve_budget_key,
)


def _settings(**safety_kwargs) -> Settings:
    return Settings(
        workspace_root=Path("/tmp"),
        artifact_root=Path("/tmp"),
        config=HarnessConfig(safety=SafetyConfig(**safety_kwargs)),
    )


# ---------------------------------------------------------------------------
# Alias table: one explicit dict, DeprecationWarning on alias use
# ---------------------------------------------------------------------------


class TestAliasTable:
    def test_aliases_map_to_canonical_caps(self):
        # Every alias resolves to a real cap name.
        for key, cap in ALIASES.items():
            assert cap in CAP_NAMES
        # The deprecated settings-style spellings are all present.
        assert ALIASES["max_iterations"] == "iterations"
        assert ALIASES["timeout_seconds"] == "wall_clock"
        assert ALIASES["max_children"] == "children"
        assert ALIASES["max_agents"] == "children"
        assert ALIASES["max_workspace_bytes"] == "workspace_bytes"
        assert ALIASES["max_messages_per_step"] == "messages_per_step"

    def test_max_agents_and_max_children_share_one_cap(self):
        # One definition, two accepted spellings, one warning.
        assert ALIASES["max_agents"] == ALIASES["max_children"] == "children"

    def test_alias_emits_deprecation_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            assert resolve_budget_key("max_iterations") == "iterations"
            assert resolve_budget_key("timeout_seconds") == "wall_clock"
            assert resolve_budget_key("max_agents") == "children"
        assert len(caught) == 3
        for w in caught:
            assert issubclass(w.category, DeprecationWarning)

    def test_canonical_cap_name_no_warning(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for cap in CAP_NAMES:
                assert resolve_budget_key(cap) == cap
        assert caught == []

    def test_unknown_key_returns_none(self):
        assert resolve_budget_key("bogus") is None
        assert resolve_budget_key(123) is None
        assert resolve_budget_key(None) is None


# ---------------------------------------------------------------------------
# ConfigResolver: one place a cap is resolved from settings
# ---------------------------------------------------------------------------


class TestConfigResolver:
    def test_defaults_from_canonical_model(self):
        r = ConfigResolver(_settings())
        # wall_clock default comes from the SafetyConfig model (single source).
        assert r.resolve("wall_clock") == SafetyConfig().timeout_seconds
        assert r.resolve("iterations") == 400
        assert r.resolve("workspace_bytes") == 1 << 20
        assert r.resolve("messages_per_step") is None

    def test_safety_field_wins(self):
        r = ConfigResolver(_settings(timeout_seconds=12.0, max_iterations=3))
        assert r.resolve("wall_clock") == 12.0
        assert r.resolve("iterations") == 3

    def test_children_max_children_wins_over_max_agents(self):
        r = ConfigResolver(_settings(max_children=5, max_agents=99))
        assert r.resolve("children") == 5

    def test_children_max_agents_fallback(self):
        # max_children unset (None) -> the deprecated max_agents alias is
        # honored as a fallback (one definition, two spellings).
        r = ConfigResolver(_settings(max_agents=7))
        assert r.resolve("children") == 7

    def test_read_cap_and_cap_limit_route_through_resolver(self):
        s = _settings(timeout_seconds=42.0)
        assert read_cap(s, "wall_clock") == 42.0
        assert cap_limit("wall_clock", s) == 42.0
        # Unknown cap name -> None.
        assert read_cap(s, "nope") is None
        assert cap_limit("nope", s) is None

    def test_none_settings_resolves_defaults(self):
        r = ConfigResolver(None)
        assert r.resolve("wall_clock") == SafetyConfig().timeout_seconds
        assert r.resolve("iterations") == 400


# ---------------------------------------------------------------------------
# agent_budgets: alias keys warn, canonical keys do not
# ---------------------------------------------------------------------------


class _FakeCtx:
    def __init__(self, budgets):
        self.budgets = budgets


class _FakeEngine:
    def __init__(self, budgets):
        self._ctx = _FakeCtx(budgets)

    def globals_for(self, agent_id):
        return {"context": self._ctx}


class TestAgentBudgets:
    def test_alias_key_warns_and_maps(self):
        engine = _FakeEngine({"max_iterations": 5})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = agent_budgets(engine, "a")
        assert out == {"iterations": 5}
        assert any(issubclass(w.category, DeprecationWarning) for w in caught)

    def test_canonical_key_no_warning(self):
        engine = _FakeEngine({"iterations": 5})
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            out = agent_budgets(engine, "a")
        assert out == {"iterations": 5}
        assert caught == []

    def test_tightest_wins_across_spellings(self):
        # max_iterations (alias) and iterations (canonical) both map to the
        # iterations cap; the smallest (tightest) wins.
        engine = _FakeEngine({"max_iterations": 9, "iterations": 4})
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out = agent_budgets(engine, "a")
        assert out == {"iterations": 4}
