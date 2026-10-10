---
id: INFO-065
type: info
title: The configuration model
summary: Two coexisting layers — layered harness.json sections and legacy env settings — what each owns, how they merge, and how safety ceilings reach the caps watchdog
date: 2026-10-10
status: current
---

# The configuration model

Two configuration layers coexist. Layered `harness.json` feeds `HarnessConfig`; env-fed `Settings` carries roots and legacy knobs.

## HarnessConfig layer

- Pydantic model with four sections: `llm`, `safety`, `agent`, `communication` (`data/config.py`).
- `harness.json.example` at repo root mirrors the schema.
- `llm`: model, base_url, OpenRouter routing, retry policy, prices, `call_timeout_seconds`.
- `safety`: timeout_seconds, max_iterations, max_agents, max_depth, max_agent_tokens, per-agent ceilings.
- `agent`: environment_notes, references_dir, skills_dir, active_turn_window, stream_children.
- `communication`: topology, registration, shared_topic, channels, digest settings, trace.

## Discovery and merge

- `_discover_config_files` collects XDG `~/.config/dynamic-harness/harness.json` first, then one local overlay.
- The overlay is the explicit `--config` path when given, else `./harness.json`.
- An explicit path replaces the cwd layer — both never merge.
- Only existing files are collected, except an explicit path, always appended.
- A missing explicit file raises at read time.
- Layers deep-merge lowest to highest (`_deep_merge`).
- Nested dicts merge field-by-field; scalars and lists replace wholesale.
- Unknown keys ignored; no file means pure defaults.
- Invalid JSON or a non-object raises `ConfigError`.

## Settings layer

- Plain dataclass `Settings` reads env plus `.env` via python-dotenv (`load_settings`).
- Fields: workspace_root, artifact_root, openai_api_key, openai_model, llm_timeout_seconds, max_turn_seconds, log_level, `config`.
- Roots knobs: `DHC_WORKSPACE_ROOT` (default cwd), `DHC_ARTIFACT_ROOT` (default `<workspace_root>/.dynamic-harness/artifacts`).
- Also `DHC_OPENAI_MODEL`, `DHC_LLM_TIMEOUT_SECONDS`, `DHC_MAX_TURN_SECONDS` (default 120), `DHC_LOG_LEVEL`.
- `get_settings()` freezes one process-wide singleton, loaded once.
- `Settings.provider` returns `config.llm` overridden by `DHC_OPENAI_MODEL` and `DHC_LLM_TIMEOUT_SECONDS`.
- `ui/terminal.py` `_apply_provider_overrides` copies `config.llm` with `--model`/`--base-url`/`--api-key`.
- `--config` installs the explicit layer onto the settings.

## Key resolution

- `merge_api_key()` reads env only, never the JSON file.
- `OPENROUTER_API_KEY` wins over `OPENAI_API_KEY`.

## Ceilings into the caps watchdog

- `framework/caps.py` `read_cap` resolves `safety.<name>` first, then a top-level settings attribute, then the default.
- Defaults: wall clock 7200.0 s, iterations 400, children 32, workspace bytes 1 MiB, messages_per_step None.
- The children ceiling reads `max_children`, falling back to `max_agents`, then 32.
- `cap_limit` maps cap names onto configured limits for crash-event payloads.
- Agent-set budgets clamp onto those ceilings via `clamp_limit` — only tighten, never loosen (`INFO-037` owns the gate).
- No consumer reads `SafetyConfig.max_agent_tokens`; the watchdog never sees it.

## Owns
- The configuration model: two layers, discovery and merge, key resolution, ceiling flow into the caps watchdog.

## Excludes
- Caps gate behavior — `INFO-037` and `INFO-061`.
- Module layout — `INFO-055`.
- Driver seam — `INFO-064`.
