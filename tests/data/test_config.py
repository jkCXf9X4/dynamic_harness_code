"""Tests for dhc.config — harness.json config, layered merge, provider view.

All config files are written under pytest's tmp_path (never into the repo).
The module-level XDG_CONFIG_DIR and the get_settings() singleton are reset per
test so a real user config or a previous test can never leak in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import dhc.data.config as config_mod
from dhc.data.config import (
    HarnessConfig,
    LLMProviderConfig,
    Settings,
    get_settings,
    load_config,
    load_settings,
    merge_api_key,
)


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch, tmp_path):
    """Point XDG discovery at tmp_path and reset the settings singleton."""
    monkeypatch.setattr(config_mod, "XDG_CONFIG_DIR", tmp_path / ".config" / "dynamic-harness")
    monkeypatch.setattr(config_mod, "_settings", None)
    yield
    monkeypatch.setattr(config_mod, "_settings", None)


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------


class TestDefaults:
    def test_default_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = load_config()
        assert isinstance(cfg, HarnessConfig)
        assert cfg.llm.model == "deepseek/deepseek-v4-flash"
        assert cfg.llm.base_url == "https://openrouter.ai/api/v1"
        assert cfg.llm.provider_ignore == []
        assert cfg.llm.provider_allow_fallbacks is True
        assert cfg.llm.provider_force is None
        assert cfg.llm.verify_ssl is True
        assert cfg.llm.price_input_per_mtok is None
        assert cfg.llm.price_output_per_mtok is None
        assert cfg.llm.call_timeout_seconds == 500.0
        assert cfg.llm.retry_max_attempts == 4
        assert cfg.llm.rate_limit_max_attempts == 6
        assert cfg.llm.retry_base_delay_seconds == 1.0
        assert cfg.llm.retry_max_delay_seconds == 30.0
        assert cfg.llm.retry_jitter_seconds == 0.5
        assert cfg.llm.rate_limit_backoff_multiplier == 3.0
        assert cfg.llm.fallback_on_rate_limit is True

    def test_default_sections_exist(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cfg = load_config()
        assert cfg.safety.timeout_seconds == 7200.0
        assert cfg.agent.active_turn_window == 50
        assert cfg.communication.topology == "off"


# ---------------------------------------------------------------------------
# Layered merge precedence: XDG < ./harness.json < --config
# ---------------------------------------------------------------------------


class TestLayeredMerge:
    def test_xdg_below_cwd(self, tmp_path, monkeypatch):
        _write(config_mod.XDG_CONFIG_DIR / "harness.json", {"llm": {"model": "xdg-model"}})
        monkeypatch.chdir(tmp_path)
        _write(tmp_path / "harness.json", {"llm": {"base_url": "https://cwd.example"}})
        cfg = load_config()
        # cwd overlay wins for its key; XDG value survives for the other key.
        assert cfg.llm.model == "xdg-model"
        assert cfg.llm.base_url == "https://cwd.example"

    def test_explicit_beats_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path / "harness.json", {"llm": {"model": "cwd-model"}})
        explicit = tmp_path / "explicit.json"
        _write(explicit, {"llm": {"model": "explicit-model"}})
        cfg = load_config(path=str(explicit))
        assert cfg.llm.model == "explicit-model"

    def test_explicit_beats_xdg(self, tmp_path, monkeypatch):
        _write(config_mod.XDG_CONFIG_DIR / "harness.json", {"llm": {"model": "xdg-model"}})
        explicit = tmp_path / "explicit.json"
        _write(explicit, {"llm": {"model": "explicit-model"}})
        cfg = load_config(path=str(explicit))
        assert cfg.llm.model == "explicit-model"

    def test_deep_merge_keeps_sibling_keys(self, tmp_path, monkeypatch):
        _write(config_mod.XDG_CONFIG_DIR / "harness.json", {"llm": {"model": "xdg-model"}})
        monkeypatch.chdir(tmp_path)
        _write(tmp_path / "harness.json", {"llm": {"base_url": "https://cwd.example"}})
        cfg = load_config()
        assert cfg.llm.model == "xdg-model"
        assert cfg.llm.base_url == "https://cwd.example"

    def test_missing_explicit_file_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(Exception):
            load_config(path=str(tmp_path / "nope.json"))

    def test_invalid_json_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        (tmp_path / "harness.json").write_text("{not json")
        with pytest.raises(Exception):
            load_config()


# ---------------------------------------------------------------------------
# Unknown keys ignored
# ---------------------------------------------------------------------------


class TestUnknownKeys:
    def test_unknown_top_level_key_ignored(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path / "harness.json", {"llm": {"model": "m"}, "bogus_section": {"x": 1}})
        cfg = load_config()
        assert cfg.llm.model == "m"
        assert not hasattr(cfg, "bogus_section")

    def test_unknown_llm_key_ignored(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path / "harness.json", {"llm": {"model": "m", "bogus_field": 42}})
        cfg = load_config()
        assert cfg.llm.model == "m"
        assert not hasattr(cfg.llm, "bogus_field")


# ---------------------------------------------------------------------------
# merge_api_key — env only, OPENROUTER wins
# ---------------------------------------------------------------------------


class TestMergeApiKey:
    def test_none_when_no_env(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        assert merge_api_key() is None

    def test_openrouter_wins_over_openai(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa")
        assert merge_api_key() == "sk-or"

    def test_openai_fallback(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-oa")
        assert merge_api_key() == "sk-oa"

    def test_never_reads_config(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.chdir(tmp_path)
        _write(tmp_path / "harness.json", {"llm": {"model": "m"}})
        cfg = load_config()
        assert merge_api_key(cfg) is None


# ---------------------------------------------------------------------------
# get_settings() backward compatibility
# ---------------------------------------------------------------------------


class TestGetSettings:
    def test_still_works_with_dhc_env_vars(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DHC_WORKSPACE_ROOT", str(tmp_path / "ws"))
        monkeypatch.setenv("DHC_ARTIFACT_ROOT", str(tmp_path / "art"))
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.setenv("DHC_OPENAI_MODEL", "env-model")
        monkeypatch.setenv("DHC_LLM_TIMEOUT_SECONDS", "12.5")
        monkeypatch.setenv("DHC_MAX_TURN_SECONDS", "99")
        monkeypatch.setenv("DHC_LOG_LEVEL", "DEBUG")
        settings = get_settings()
        assert settings.workspace_root == tmp_path / "ws"
        assert settings.artifact_root == tmp_path / "art"
        assert settings.openai_api_key == "sk-test"
        assert settings.openai_model == "env-model"
        assert settings.llm_timeout_seconds == 12.5
        assert settings.max_turn_seconds == 99.0
        assert settings.log_level == "DEBUG"

    def test_singleton_cached(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        first = get_settings()
        second = get_settings()
        assert first is second

    def test_defaults_without_env(self, tmp_path, monkeypatch):
        """View semantics (W5.1): with no env, the view reflects the
        canonical HarnessConfig defaults (not the legacy gpt-4o/60.0)."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("DHC_WORKSPACE_ROOT", raising=False)
        monkeypatch.delenv("DHC_ARTIFACT_ROOT", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("DHC_OPENAI_MODEL", raising=False)
        monkeypatch.delenv("DHC_LLM_TIMEOUT_SECONDS", raising=False)
        monkeypatch.delenv("DHC_MAX_TURN_SECONDS", raising=False)
        monkeypatch.delenv("DHC_LOG_LEVEL", raising=False)
        settings = get_settings()
        # The view delegates to the canonical config defaults.
        assert settings.openai_model == "deepseek/deepseek-v4-flash"
        assert settings.llm_timeout_seconds == 500.0
        assert settings.max_turn_seconds == 120.0
        assert settings.log_level == "INFO"


# ---------------------------------------------------------------------------
# Settings.provider view
# ---------------------------------------------------------------------------


class TestProviderView:
    def test_provider_reflects_config_llm(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path / "harness.json", {"llm": {"model": "cfg-model", "base_url": "https://cfg.example"}})
        settings = Settings(workspace_root=tmp_path, artifact_root=tmp_path, config=load_config())
        assert isinstance(settings.provider, LLMProviderConfig)
        assert settings.provider.model == "cfg-model"
        assert settings.provider.base_url == "https://cfg.example"
        assert settings.provider.call_timeout_seconds == 500.0
        assert settings.provider.retry_max_attempts == 4

    def test_provider_env_overrides_config(self, tmp_path, monkeypatch):
        """View semantics (W5.1): the DHC_* env bridge is applied in
        load_settings (the single env bridge), not in Settings construction.
        A directly-constructed Settings is a pure view over its config."""
        monkeypatch.chdir(tmp_path)
        _write(tmp_path / "harness.json", {"llm": {"model": "cfg-model", "call_timeout_seconds": 500.0}})
        monkeypatch.setenv("DHC_OPENAI_MODEL", "env-model")
        monkeypatch.setenv("DHC_LLM_TIMEOUT_SECONDS", "30")
        # The env bridge runs in load_settings: the view reflects the
        # bridged config.
        settings = load_settings()
        assert settings.provider.model == "env-model"
        assert settings.provider.call_timeout_seconds == 30.0
        # A directly-constructed Settings is a pure view (no env read):
        # it reflects the config file, not the env.
        direct = Settings(workspace_root=tmp_path, artifact_root=tmp_path, config=load_config())
        assert direct.provider.model == "cfg-model"
        assert direct.provider.call_timeout_seconds == 500.0

    def test_provider_defaults_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        settings = Settings(workspace_root=tmp_path, artifact_root=tmp_path)
        assert settings.provider.model == "deepseek/deepseek-v4-flash"
        assert settings.provider.base_url == "https://openrouter.ai/api/v1"


# ---------------------------------------------------------------------------
# DHC_* env bridge — single read site (W5.1)
# ---------------------------------------------------------------------------


class TestEnvBridge:
    def test_bridge_applied_in_load_settings(self, tmp_path, monkeypatch):
        """The DHC_* env vars are bridged in ONE place (load_settings)."""
        monkeypatch.chdir(tmp_path)
        _write(tmp_path / "harness.json", {"llm": {"model": "cfg-model"}})
        monkeypatch.setenv("DHC_OPENAI_MODEL", "env-model")
        monkeypatch.setenv("DHC_LLM_TIMEOUT_SECONDS", "30")
        settings = load_settings()
        # The bridge overrode the config file values.
        assert settings.config.llm.model == "env-model"
        assert settings.config.llm.call_timeout_seconds == 30.0
        # The view reflects the bridged config.
        assert settings.openai_model == "env-model"
        assert settings.llm_timeout_seconds == 30.0

    def test_bridge_noop_without_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(tmp_path / "harness.json", {"llm": {"model": "cfg-model"}})
        monkeypatch.delenv("DHC_OPENAI_MODEL", raising=False)
        monkeypatch.delenv("DHC_LLM_TIMEOUT_SECONDS", raising=False)
        settings = load_settings()
        assert settings.config.llm.model == "cfg-model"
        assert settings.config.llm.call_timeout_seconds == 500.0

    def test_bridge_invalid_timeout_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("DHC_LLM_TIMEOUT_SECONDS", "not-a-number")
        with pytest.raises(Exception):
            load_settings()

    def test_env_vars_read_only_in_config_module(self, tmp_path, monkeypatch):
        """Acceptance: DHC_* config env vars are read only in config.py.

        The provider view and Settings construction do NOT read the env —
        only load_settings (via _apply_env_bridge) does.
        """
        monkeypatch.chdir(tmp_path)
        _write(tmp_path / "harness.json", {"llm": {"model": "cfg-model"}})
        monkeypatch.setenv("DHC_OPENAI_MODEL", "env-model")
        # Direct construction: pure view, no env read.
        settings = Settings(workspace_root=tmp_path, artifact_root=tmp_path, config=load_config())
        assert settings.openai_model == "cfg-model"
        assert settings.provider.model == "cfg-model"


# ---------------------------------------------------------------------------
# W5.3: harness.json.example is generated from HarnessConfig (freshness)
# ---------------------------------------------------------------------------


class TestExampleFile:
    """The example file is generated from the model, not hand-maintained.

    Every HarnessConfig field (every section, every field) must appear in
    ``harness.json.example``, and the file must match what the generator
    script produces (so it can never drift from the model).
    """

    @pytest.fixture()
    def example_text(self):
        example_path = Path(__file__).resolve().parents[2] / "harness.json.example"
        assert example_path.exists(), "harness.json.example is missing"
        return example_path.read_text()

    def test_every_field_appears(self, example_text):
        """Every field of every section appears in the example file."""
        data = json.loads(example_text)
        for section, section_model in HarnessConfig.model_fields.items():
            assert section in data, f"section {section!r} missing from example"
            # The section's model is the annotation (a BaseModel subclass).
            section_cls = section_model.annotation
            for field_name in section_cls.model_fields:
                assert field_name in data[section], (
                    f"field {section}.{field_name} missing from example"
                )

    def test_example_matches_generator(self, example_text):
        """The checked-in file matches the generator output (freshness)."""
        import importlib.util

        gen_path = (
            Path(__file__).resolve().parents[2] / "tools" / "generate_harness_example.py"
        )
        spec = importlib.util.spec_from_file_location("gen_harness_example", gen_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert example_text == module.render_example(), (
            "harness.json.example is stale — run "
            "python3 tools/generate_harness_example.py"
        )


# ---------------------------------------------------------------------------
# Config file overrides defaults
# ---------------------------------------------------------------------------


class TestConfigOverrides:
    def test_llm_section_overrides_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        _write(
            tmp_path / "harness.json",
            {
                "llm": {
                    "model": "custom/model",
                    "base_url": "https://custom.example/v1",
                    "call_timeout_seconds": 123.0,
                    "retry_max_attempts": 7,
                    "rate_limit_max_attempts": 9,
                    "fallback_on_rate_limit": False,
                }
            },
        )
        cfg = load_config()
        assert cfg.llm.model == "custom/model"
        assert cfg.llm.base_url == "https://custom.example/v1"
        assert cfg.llm.call_timeout_seconds == 123.0
        assert cfg.llm.retry_max_attempts == 7
        assert cfg.llm.rate_limit_max_attempts == 9
        assert cfg.llm.fallback_on_rate_limit is False
        # untouched defaults survive
        assert cfg.llm.provider_allow_fallbacks is True
        assert cfg.llm.verify_ssl is True

# ---------------------------------------------------------------------------
# IMP-001 Step 5: ceiling-cap defaults on SafetyConfig
# ---------------------------------------------------------------------------


def test_caps_defaults_present(tmp_path, monkeypatch):
    """load_config().safety exposes the new ceiling-cap fields with defaults."""
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    safety = cfg.safety
    assert safety.max_workspace_bytes is None
    assert safety.max_children is None
    assert safety.max_messages_per_step is None
    # Existing defaults unchanged.
    assert safety.timeout_seconds == 7200.0
    assert safety.max_iterations == 400
    assert safety.max_agent_tokens is None
    assert safety.max_agents == 300
    assert safety.max_depth == 15
