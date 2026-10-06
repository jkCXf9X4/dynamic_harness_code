"""Runtime configuration for dhc.

A plain dataclass (pydantic-settings is not a dependency). Values are read
from the environment and an optional ``.env`` file (via python-dotenv), then
frozen into a process-wide singleton by :func:`get_settings`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

from dotenv import load_dotenv

from .errors import ConfigError


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
    )


_settings: Optional[Settings] = None


def get_settings(env: Optional[Mapping[str, str]] = None) -> Settings:
    """Return the process-wide :class:`Settings` singleton (loaded once)."""
    global _settings
    if _settings is None:
        _settings = load_settings(env)
    return _settings