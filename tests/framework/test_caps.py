"""W5.2: the single alias table + ConfigResolver (caps.py).

The 11 ad-hoc ``_BUDGET_CAP_KEYS`` aliases collapse to one explicit
:data:`~dhc.framework.caps.ALIASES` table with a :class:`DeprecationWarning`
on alias use, and cap ceilings resolve through one
:class:`~dhc.framework.caps.ConfigResolver` (W5.1).
"""

from __future__ import annotations

import time
import warnings
from pathlib import Path

import pytest

from dhc.data.config import HarnessConfig, SafetyConfig, Settings, load_settings
from dhc.framework.caps import (
    ALIASES,
    CAP_NAMES,
    ConfigResolver,
    agent_budgets,
    cap_hit,
    cap_limit,
    read_cap,
    reset_workspace_baseline,
    resolve_budget_key,
    workspace_file_bytes,
    workspace_scan_truncated,
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


# ---------------------------------------------------------------------------
# workspace_bytes: REPL state + files the agent wrote (bash included)
# ---------------------------------------------------------------------------


class _NamespaceEngine:
    """Minimal engine: a fixed REPL namespace, no budgets."""

    def __init__(self, namespace=None):
        self._namespace = namespace or {}

    def globals_for(self, agent_id):
        return dict(self._namespace)


def _ws_settings(root, **safety_kwargs) -> Settings:
    return Settings(
        workspace_root=Path(root),
        artifact_root=Path(root),
        workspace_root_explicit=True,
        config=HarnessConfig(safety=SafetyConfig(**safety_kwargs)),
    )


def _ws_hit(settings, namespace=None):
    return cap_hit(
        "a",
        _NamespaceEngine(namespace),
        0,
        time.monotonic(),
        settings=settings,
        child_count=lambda: 0,
        pending_messages=lambda: 0,
    )


def _write(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class TestWorkspaceFootprint:
    @pytest.fixture(autouse=True)
    def _fresh_baseline(self):
        reset_workspace_baseline()
        yield
        reset_workspace_baseline()

    def test_large_repl_state_trips(self, tmp_path):
        settings = _ws_settings(tmp_path, max_workspace_bytes=500)
        hit = _ws_hit(settings, {"blob": "x" * 2000})
        assert hit == {
            "cap": "workspace_bytes",
            "limit": 500,
            "source": "ceiling",
        }

    def test_file_written_in_workspace_trips(self, tmp_path):
        settings = _ws_settings(tmp_path, max_workspace_bytes=1000)
        assert _ws_hit(settings) is None  # baseline snapshot taken here
        _write(tmp_path / "dump.bin", 2000)
        hit = _ws_hit(settings)
        assert hit is not None and hit["cap"] == "workspace_bytes"
        assert hit["limit"] == 1000

    def test_filesystem_growth_alone_trips(self, tmp_path):
        # The REPL state is empty: nothing but the file can trip the cap.
        settings = _ws_settings(tmp_path, max_workspace_bytes=1000)
        assert _ws_hit(settings, {}) is None
        _write(tmp_path / "from_bash.log", 4096)
        hit = _ws_hit(settings, {})
        assert hit is not None and hit["cap"] == "workspace_bytes"

    def test_nested_directory_growth_trips(self, tmp_path):
        settings = _ws_settings(tmp_path, max_workspace_bytes=1000)
        assert _ws_hit(settings) is None
        nested = tmp_path / "a" / "b" / "c" / "d" / "e"
        for index in range(3):
            _write(nested / f"part{index}.bin", 800)
        hit = _ws_hit(settings)
        assert hit is not None and hit["cap"] == "workspace_bytes"

    def test_growth_of_existing_file_counts(self, tmp_path):
        existing = tmp_path / "notes.txt"
        _write(existing, 100)
        settings = _ws_settings(tmp_path, max_workspace_bytes=1000)
        assert _ws_hit(settings) is None
        with existing.open("ab") as handle:
            handle.write(b"y" * 2000)
        assert _ws_hit(settings) is not None

    def test_preexisting_files_do_not_count(self, tmp_path):
        # A checked-out tree is not the agent's footprint: the baseline is
        # taken on the first measurement, so only new/grown files count.
        _write(tmp_path / "vendor" / "big.bin", 50_000)
        settings = _ws_settings(tmp_path, max_workspace_bytes=1000)
        assert _ws_hit(settings) is None
        assert workspace_file_bytes(settings) == 0

    def test_pruned_directories_are_ignored(self, tmp_path):
        settings = _ws_settings(tmp_path, max_workspace_bytes=1000)
        assert _ws_hit(settings) is None
        _write(tmp_path / ".git" / "objects" / "pack.bin", 50_000)
        _write(tmp_path / "node_modules" / "dep" / "index.js", 50_000)
        _write(tmp_path / "__pycache__" / "mod.pyc", 50_000)
        assert _ws_hit(settings) is None

    def test_unusable_root_measures_zero(self, tmp_path):
        missing = tmp_path / "gone"
        settings = _ws_settings(missing, max_workspace_bytes=10)
        assert workspace_file_bytes(settings) == 0
        assert _ws_hit(settings) is None

    def test_implicit_cwd_root_is_not_scanned(self, tmp_path):
        # Default (implicit) root: the interpreter's cwd is not the agent's
        # workspace, so files never count — only REPL state does.
        settings = Settings(
            workspace_root=Path(tmp_path),
            artifact_root=Path(tmp_path),
            config=HarnessConfig(safety=SafetyConfig(max_workspace_bytes=1000)),
        )
        assert settings.workspace_root_explicit is False
        _write(tmp_path / "ignored.bin", 50_000)
        assert workspace_file_bytes(settings) == 0
        assert _ws_hit(settings) is None

    def test_load_settings_sets_explicit_flag(self, tmp_path):
        explicit = load_settings(env={"DHC_WORKSPACE_ROOT": str(tmp_path)})
        assert explicit.workspace_root == tmp_path
        assert explicit.workspace_root_explicit is True
        implicit = load_settings(env={})
        assert implicit.workspace_root == Path.cwd()
        assert implicit.workspace_root_explicit is False

    def test_truncated_baseline_disables_accounting_without_trip(
        self, tmp_path, monkeypatch
    ):
        # A baseline scan that hits the deadline is unusable (it would count
        # pre-existing files as growth): accounting is off, no forced trip.
        monkeypatch.setattr("dhc.framework.caps._WORKSPACE_SCAN_DEADLINE_SECONDS", -1)
        settings = _ws_settings(tmp_path, max_workspace_bytes=1000)
        _write(tmp_path / "big.bin", 50_000)
        assert workspace_file_bytes(settings) == 0
        assert workspace_scan_truncated(settings) is True
        assert _ws_hit(settings) is None

    def test_truncated_scan_reports_partial_without_trip(self, tmp_path, monkeypatch):
        settings = _ws_settings(tmp_path, max_workspace_bytes=1000)
        assert _ws_hit(settings) is None  # clean baseline
        _write(tmp_path / "growth.bin", 50_000)
        monkeypatch.setattr("dhc.framework.caps._WORKSPACE_SCAN_DEADLINE_SECONDS", -1)
        # Truncation alone never produces a hit; the partial count is reported.
        assert _ws_hit(settings) is None
        assert workspace_file_bytes(settings) == 0
        assert workspace_scan_truncated(settings) is True
