---
id: INFO-066
type: info
title: Unwired modules
summary: Modules present and tested but not composed into build_runtime — trace persistence and the superseded structured-prompt composition
date: 2026-10-10
status: current
---

# Unwired modules

Two modules ship importable and tested, yet composed into no runtime.
`build_runtime` (`src/dhc/wiring.py`) wires neither.

## Per-agent trace persistence

- `src/dhc/data/trace.py` provides `TraceStore` and `TracingEngine`.
- `TraceStore` appends one JSON line per entry to `<trace_root>/<agent_id>/trace.jsonl`.
- Entry types: `llm_request`, `llm_response`, `tool_call`, `tool_result`, `event`.
- Each entry carries `ts` (ms), `timestamp` (ISO), `type`, plus caller data.
- Writes are best-effort: failures log, never raise.
- `TracingEngine` wraps any engine matching `execute(agent_id, code, namespace, timeout)`.
  - Records `tool_call` before delegating.
  - Records `tool_result` after.
  - Returns the wrapped result unchanged.

## Structured prompt composition

- `src/dhc/llm/prompts.py` composes the structured "presetup" prompt layout.
- `AGENT_SYSTEM_PROMPT` loads from `agent_system_prompt.txt`, with an inline fallback.
- `ORCHESTRATOR_SYSTEM_PROMPT` is the delegation-only directive for role `orchestrator`.
- Builders: `build_system_prompt`, `build_steerage`, `build_user_message`, `compose_initial_prompt`.
- Superseded by the workspace `build_prompt` citizen from the driver seam (`INFO-064`).

## Disposition

- Both modules are importable and covered by tests.
- Trace tests live in `tests/ui/test_checkpoint_trace.py`.
- Prompt tests live in `tests/llm/test_prompts.py`.
- No module under `src/` imports `dhc.data.trace` or `dhc.llm.prompts`.
- `build_runtime` composes neither: no trace store, no tracing engine, no prompt builders.

## Owns
- Disposition of present-but-uncomposed modules: what each does, and that `build_runtime` composes none of it.

## Excludes
- The driver seam that builds prompts: `INFO-064`.
- The module map placing these modules: `INFO-055`.
