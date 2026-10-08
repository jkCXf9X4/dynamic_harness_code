"""Runtime configuration for dhc.

Two layers:

* A plain dataclass :class:`Settings` (pydantic-settings is not a
  dependency). Values are read from the environment and an optional ``.env``
  file (via python-dotenv), then frozen into a process-wide singleton by
  :func:`get_settings`.
* A Pydantic-validated JSON config file (``harness.json``) with layered
  discovery: XDG user-global (``~/.config/dynamic-harness/harness.json``) →
  working-directory ``./harness.json`` → explicit ``--config PATH``. Layers
  are deep-merged (lowest → highest precedence) and unknown keys are ignored.
  The API key is env-only — never stored in the JSON file.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from ..errors import ConfigError


DEFAULT_CONFIG_FILENAME = "harness.json"
XDG_CONFIG_DIR = Path.home() / ".config" / "dynamic-harness"


# ---------------------------------------------------------------------------
# harness.json schema (Pydantic-validated)
# ---------------------------------------------------------------------------


class LLMProviderConfig(BaseModel):
    """Provider settings for the ``llm`` section of ``harness.json``."""

    model: str = "deepseek/deepseek-v4-flash"
    base_url: str = "https://openrouter.ai/api/v1"
    provider_ignore: list[str] = Field(default_factory=list)
    provider_allow_fallbacks: bool = True
    provider_force: str | None = Field(
        default=None,
        description="OpenRouter provider slug to pin exclusively (disables fallbacks).",
    )
    verify_ssl: bool = True
    price_input_per_mtok: float | None = Field(
        default=None, description="USD per 1M input tokens, if known"
    )
    price_output_per_mtok: float | None = Field(
        default=None, description="USD per 1M output tokens, if known"
    )
    call_timeout_seconds: float = Field(
        default=500.0, gt=0,
        description="Timeout for a single LLM request, in seconds.",
    )
    retry_max_attempts: int = Field(
        default=4, ge=1,
        description="How many times a single LLM call may be retried after a "
                    "generic transient failure (timeout, connection drop, 5xx).",
    )
    rate_limit_max_attempts: int = Field(
        default=6, ge=1,
        description="How many times a single LLM call may be retried after a "
                    "rate limit (HTTP 429 / engine_overloaded).",
    )
    retry_base_delay_seconds: float = Field(
        default=1.0, gt=0.0,
        description="Base sleep before the first retry, in seconds.",
    )
    retry_max_delay_seconds: float = Field(
        default=30.0, gt=0.0,
        description="Upper bound on any single retry sleep, in seconds.",
    )
    retry_jitter_seconds: float = Field(
        default=0.5, ge=0.0,
        description="Maximum random jitter added to each retry sleep, in seconds.",
    )
    rate_limit_backoff_multiplier: float = Field(
        default=3.0, gt=0.0,
        description="Scales the exponential backoff for rate-limited calls.",
    )
    fallback_on_rate_limit: bool = Field(
        default=True,
        description="When a call fails with a rate limit, retry without the "
                    "rate-limited provider.",
    )


class SafetyConfig(BaseModel):
    """Safety limits for the ``safety`` section of ``harness.json``."""

    timeout_seconds: float = Field(default=7200.0, gt=0)
    max_iterations: int = Field(default=400, ge=1)
    max_agent_tokens: int | None = None
    max_agents: int = Field(default=300, ge=1)
    max_depth: int = Field(default=15, ge=1)
    # IMP-001 Step 5: ceiling caps (per-agent; None = runtime default).
    max_workspace_bytes: int | None = Field(
        default=None, ge=1,
        description="Per-agent workspace ceiling in bytes (None = runtime default 1 MiB).",
    )
    max_children: int | None = Field(
        default=None, ge=1,
        description="Per-agent child cap (None = runtime default 32).",
    )
    max_messages_per_step: int | None = Field(
        default=None, ge=1,
        description="Message-rate cap per step (None = disabled).",
    )


class AgentConfig(BaseModel):
    """Agent behaviour for the ``agent`` section of ``harness.json``."""

    environment_notes: list[str] = Field(default_factory=list)
    references_dir: str | None = None
    skills_dir: str | None = None
    active_turn_window: int = Field(default=50, ge=1)
    stream_children: bool = True


class CommunicationConfig(BaseModel):
    """Communication settings for the ``communication`` section of ``harness.json``."""

    topology: str = "off"
    registration: str = "parent"
    shared_topic: str = "shared"
    channels: list[str] = Field(default_factory=list)
    digest_mode: str = "pull"
    digest_max_items: int = Field(default=5, ge=1)
    digest_max_tokens: int = Field(default=400, ge=1)
    trace: bool = True


class HarnessConfig(BaseModel):
    """Pydantic-validated ``harness.json`` configuration."""

    llm: LLMProviderConfig = Field(default_factory=LLMProviderConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    communication: CommunicationConfig = Field(default_factory=CommunicationConfig)


# ---------------------------------------------------------------------------
# Layered discovery + deep merge
# ---------------------------------------------------------------------------


def _discover_config_files(explicit: str | None = None) -> list[Path]:
    """Config files to merge, from lowest (common base) to highest (local overlay).

    The XDG user-global ``harness.json``
    (``~/.config/dynamic-harness/harness.json``) acts as the common base shared
    across all projects; the working-directory ``harness.json`` — or an explicit
    ``--config`` path — is the local overlay that overrides it. Only files that
    exist are collected, except an explicit path is always appended so a missing
    explicit file still raises when read.
    """
    files: list[Path] = []
    xdg_candidate = XDG_CONFIG_DIR / DEFAULT_CONFIG_FILENAME
    if xdg_candidate.exists():
        files.append(xdg_candidate)
    if explicit:
        files.append(Path(explicit))
    else:
        cwd_candidate = Path.cwd() / DEFAULT_CONFIG_FILENAME
        if cwd_candidate.exists():
            files.append(cwd_candidate)
    return files


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge ``overlay`` into ``base`` and return a new dict.

    Nested dicts merge field-by-field (a local ``{"llm": {"model": "..."}}``
    keeps the base's other ``llm`` keys), so a local config can override just one
    setting inside a section. Anything else in the overlay — scalars and lists
    alike — replaces the base value wholesale.
    """
    result = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | None = None) -> HarnessConfig:
    """Load the layered ``harness.json`` config (XDG → ``./harness.json`` → *path*).

    Unknown keys are ignored by Pydantic. Returns defaults when no config file
    exists. Raises :class:`ConfigError` on invalid JSON or a non-object file.
    """
    files = _discover_config_files(path)
    if not files:
        return HarnessConfig()
    merged: dict = {}
    for cfg_path in files:
        try:
            raw = json.loads(cfg_path.read_text())
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Invalid JSON in config file '{cfg_path}': {exc}") from exc
        if not isinstance(raw, dict):
            raise ConfigError(f"Config file '{cfg_path}' must contain a JSON object")
        merged = _deep_merge(merged, raw)
    return HarnessConfig.model_validate(merged)


def merge_api_key(config: HarnessConfig | None = None) -> str | None:
    """Return the API key from env only — never from the JSON config.

    ``OPENROUTER_API_KEY`` wins over ``OPENAI_API_KEY``.
    """
    return os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")


# ---------------------------------------------------------------------------
# Legacy Settings dataclass (backward compatible)
# ---------------------------------------------------------------------------


@dataclass
class Settings:
    """Resolved dhc settings."""

    workspace_root: Path
    artifact_root: Path
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"
    llm_timeout_seconds: float = 60.0
    max_turn_seconds: float = 120.0
    log_level: str = "INFO"
    config: HarnessConfig = field(default_factory=HarnessConfig)

    @property
    def provider(self) -> LLMProviderConfig:
        """Provider view: ``config.llm`` overridden by DHC_OPENAI_MODEL / DHC_LLM_TIMEOUT_SECONDS.

        Precedence: explicit CLI args (caller-supplied) → config file → env vars
        → defaults. The env overrides here mirror the legacy ``DHC_*`` knobs so
        existing deployments keep working while the canonical source is the
        ``llm`` section of ``harness.json``.
        """
        updates: dict = {}
        model = os.environ.get("DHC_OPENAI_MODEL")
        if model:
            updates["model"] = model
        timeout = os.environ.get("DHC_LLM_TIMEOUT_SECONDS")
        if timeout:
            try:
                updates["call_timeout_seconds"] = float(timeout)
            except ValueError as exc:
                raise ConfigError(
                    f"DHC_LLM_TIMEOUT_SECONDS must be a number, got {timeout!r}"
                ) from exc
        return self.config.llm.model_copy(update=updates)


def load_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Build a :class:`Settings` from *env* (default: os.environ + .env)."""
    if env is None:
        load_dotenv()
        env = os.environ

    workspace_root = Path(env.get("DHC_WORKSPACE_ROOT", str(Path.cwd())))
    artifact_root = Path(
        env.get("DHC_ARTIFACT_ROOT", str(workspace_root / ".dynamic-harness" / "artifacts"))
    )

    def _float(name: str, default: float) -> float:
        raw = env.get(name)
        if raw is None or raw == "":
            return default
        try:
            return float(raw)
        except ValueError as exc:
            raise ConfigError(f"{name} must be a number, got {raw!r}") from exc

    return Settings(
        workspace_root=workspace_root,
        artifact_root=artifact_root,
        openai_api_key=env.get("OPENAI_API_KEY", ""),
        openai_model=env.get("DHC_OPENAI_MODEL", "gpt-4o"),
        llm_timeout_seconds=_float("DHC_LLM_TIMEOUT_SECONDS", 60.0),
        max_turn_seconds=_float("DHC_MAX_TURN_SECONDS", 120.0),
        log_level=env.get("DHC_LOG_LEVEL", "INFO"),
        config=load_config(),
    )


_settings: Optional[Settings] = None


def get_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Return the process-wide :class:`Settings` singleton (loaded once)."""
    global _settings
    if _settings is None:
        _settings = load_settings(env)
    return _settings