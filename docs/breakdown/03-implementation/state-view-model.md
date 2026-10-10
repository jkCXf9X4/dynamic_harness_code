---
id: INFO-059
type: info
title: State view model
summary: Operator state view-model - what ui/state.py builds from the runtime, the enum-driven event-kind mapping, the token/cost provenance seams feeding it
date: 2026-10-09
status: current
---

# State view model

- `src/dhc/ui/state.py` builds the operator's review files from the live runtime.
  - Review files: `agents.txt`, `stats.json`, `events.jsonl`, `trace.jsonl`.
- **Peripheral view-model**:
  - Contract (module docstring): "must never crash a snapshot".
  - So `on_event` never raises on an unknown kind.
  - Unknown kind records as activity (throttled).
  - Documented fallback also tolerates non-enum kinds via `str(kind)`.

## Event-kind mapping

- **`TERMINAL_EVENT_KINDS: dict[EventKind, str]`**:
  - Single source of truth for terminal snapshot kinds.
  - Terminal means force snapshot plus a dedicated record.
  - Today holds one member: `EventKind.escalation`.
  - Emitted at `tooling/channels.py:234`.
- Table keyed by `EventKind` member, not by string value.
  - Renaming a member without updating the table: import-time `AttributeError`, never a silent drop.
  - Renaming a member's value: visible table diff.
- `on_event` routes a kind to the terminal path if and only if `isinstance(kind, EventKind) and kind in TERMINAL_EVENT_KINDS`.
  - Every other kind (enum or not) records as activity.
- New `EventKind` member records as activity by default, never dropped.
  - Promoting it to terminal: deliberate, test-pinned change (`tests/ui/test_state.py`).
- Old `"report"`/`"failure"` string branches preceding the table: dead code, now removed.
  - `EventKind` has no such members.
  - Typed bus validates `Event.kind: EventKind`.

## Token/cost provenance

- **Write seam**:
  - `LLMDriver.__call__` reads the client's `_last_usage`/`_last_cost` after a successful `generate_code_block`.
  - Then calls `agent.record_usage(usage, cost_usd)`.
  - Single place provider usage flows into agent state.
- **Accumulation point**:
  - `Agent.record_usage` adds `prompt_tokens`/`completion_tokens`/`cached_tokens` into per-agent accumulators.
  - Adds `cost_usd` into a running total.
  - None-safe: a `None` usage or missing key contributes nothing.
- **Read seam**:
  - `build_agent_tree` copies accumulated usage into `AgentNode` (`tokens = prompt + completion`).
  - `build_stats` aggregates the node values into `Stats`.
  - So `stats.json` reports real totals.
- **Mock path reports zeros**:
  - `MockDriver`/`MockLLM` never set usage.
  - So `record_usage` is never called.
  - View-model renders zero defaults (`AgentNode.usage` renders the empty string).
- `cost_usd`: provider estimate, not a billing figure.
  - View-model reports it as such.
- **Open**: whether `messages` (also inert) is populated from the same seam.
- **Open**: whether `context_tokens` derives from the digest size (`framework/context.py`, `DIGEST_KEEP`) or the provider's `prompt_tokens`.
  - Seam shaped so either can be added without a second write path.

## Owns
- The state view-model: what `ui/state.py` builds, the enum-driven terminal mapping, the token/cost provenance seams (write, accumulate, read).

## Excludes
- Event-stream discipline delivering events to the writer: `INFO-048`, `INFO-051`.
- Module layout placing the writer in `ui/`: `INFO-055`.
- Decisions setting the mapping and the seams: `IMD-002`, `IMD-003`.
