---
id: INFO-065
type: info
title: The configuration model
summary: One canonical config — HarnessConfig from layered harness.json — with Settings as a read-only view, the env bridge, CLI overrides, and safety ceilings reaching the caps watchdog
date: 2026-10-10
status: current
---

# The configuration model

One canonical config: `HarnessConfig` (Pydantic, from layered `harness.json`). `Settings` is a read-only view over it, not a parallel source (W5.1).

## HarnessConfig — canonical

- Pydantic model with four sections: `llm`, `safety`, `agent`, `communication` (`data/config.py`).
- `harness.json.example` at repo root is GENERATED from `HarnessConfig` by `tools/generate_harness_example.py` — not hand-maintained.
- Freshness test: `tests/data/test_config.py::TestExampleFile` — every field appears, and the file must match the generator output.
- `llm`: model, base_url, OpenRouter routing, retry policy, prices, `call_timeout_seconds`.
- `safety`: timeout_seconds, max_iterations, max_children (`max_agents` is its deprecated alias), max_depth, max_agent_tokens, per-agent ceilings.
- `agent`: environment_notes, references_dir, skills_dir, active_turn_window, stream_children.
- `communication`: topology, registration, shared_topic, channels, digest settings, trace.

## Discovery and merge

- `_discover_config_files` collects XDG `~/.config/dynamic-harness/harness.json` first, then one local overlay.
- The overlay is the explicit `--config` path when given, else `./harness.json`.
- `--config PATH` is the highest-precedence config layer; it replaces the cwd layer — both never merge.
- Only existing files are collected, except an explicit path, always appended.
- A missing explicit file raises at read time.
- Layers deep-merge lowest to highest (`_deep_merge`).
- Nested dicts merge field-by-field; scalars and lists replace wholesale.
- Unknown keys ignored; no file means pure defaults.
- Invalid JSON or a non-object raises `ConfigError`.

## Settings — read-only view

- Plain dataclass `Settings` wraps one `HarnessConfig` (`load_settings`); the legacy names are read-only properties over it.
- Fields: workspace_root, artifact_root, openai_api_key, max_turn_seconds, log_level, `config`.
- Properties: `openai_model` (over `config.llm.model`), `llm_timeout_seconds` (over `config.llm.call_timeout_seconds`), `provider` (over `config.llm`).
- Roots knobs: `DHC_WORKSPACE_ROOT` (default cwd), `DHC_ARTIFACT_ROOT` (default `<workspace_root>/.dynamic-harness/artifacts`).
- Also `DHC_MAX_TURN_SECONDS` (default 120), `DHC_LOG_LEVEL`.
- The DHC_* env bridge is applied ONCE in `load_settings` (`_apply_env_bridge`): `DHC_OPENAI_MODEL` / `DHC_LLM_TIMEOUT_SECONDS` override the `llm` section. Precedence: env > config file > defaults.
- `get_settings()` freezes one process-wide singleton, loaded once.
- `ui/terminal.py` `_apply_provider_overrides`: `--model`/`--base-url`/`--api-key` override the provider config (copied onto `config.llm`).
- `--config` installs the explicit layer onto the settings.

## Key resolution

- `merge_api_key()` reads env only, never the JSON file.
- `OPENROUTER_API_KEY` wins over `OPENAI_API_KEY`.

## Ceilings into the caps watchdog

- `framework/caps.py` `read_cap` resolves through `ConfigResolver`: `safety.<field>` wins, then the runtime default.
- Defaults: wall clock 7200.0 s (from the canonical `SafetyConfig` model), iterations 400, children 32, workspace bytes 1 MiB, messages_per_step None.
- The children ceiling reads `max_children`, falling back to the deprecated `max_agents` alias, then 32.
- `ALIASES` maps deprecated settings-style budget keys onto canonical cap names; use emits a `DeprecationWarning` (W5.2).
- `cap_limit` maps cap names onto configured limits for crash-event payloads.
- Agent-set budgets clamp onto those ceilings via `clamp_limit` — only tighten, never loosen (`INFO-037` owns the gate).
- No consumer reads `SafetyConfig.max_agent_tokens`; the watchdog never sees it.

## Owns
- The configuration model: the canonical `HarnessConfig`, discovery and merge, the `Settings` view, key resolution, ceiling flow into the caps watchdog.

## Excludes
- Caps gate behavior — `INFO-037` and `INFO-061`.
- Module layout — `INFO-055`.
- Driver seam — `INFO-064`.
