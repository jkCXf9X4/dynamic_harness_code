---
id: INFO-059
type: info
title: State view model
summary: The operator's state view-model — what ui/state.py builds from the runtime, the enum-driven event-kind mapping, and the token/cost provenance seams that feed it
date: 2026-10-09
status: current
---

# State view model

`src/dhc/ui/state.py` builds the operator's review files (`agents.txt`,
`stats.json`, `events.jsonl`, `trace.jsonl`) from the live runtime. It is a
peripheral view-model: its contract is "must never crash a snapshot" (module
docstring), so `on_event` never raises on an unknown kind — it records it as
activity (throttled), the documented fallback that also tolerates non-enum
kinds via `str(kind)`.

## Event-kind mapping

- `TERMINAL_EVENT_KINDS: dict[EventKind, str]` is the single source of truth
  for which kinds the snapshot records as terminal (force snapshot plus a
  dedicated record). Today it holds one member: `EventKind.escalation`
  (emitted at `tooling/channels.py:234`).
- The table is keyed by `EventKind` member, not by string value: renaming a
  member name without updating the table is an import-time `AttributeError`,
  never a silent drop. Renaming a member's value is a visible table diff.
- `on_event` routes a kind to the terminal path iff
  `isinstance(kind, EventKind) and kind in TERMINAL_EVENT_KINDS`; every other
  kind (enum or not) records as activity.
- A new `EventKind` member is recorded as activity by default (never
  dropped); promoting it to terminal is a deliberate, test-pinned change
  (`tests/ui/test_state.py`).
- The `"report"`/`"failure"` string branches that preceded the table were
  dead code — `EventKind` has no such members and the typed bus validates
  `Event.kind: EventKind` — and are removed.

## Token/cost provenance

- One write seam: `LLMDriver.__call__` reads the client's
  `_last_usage`/`_last_cost` after a successful `generate_code_block` and
  calls `agent.record_usage(usage, cost_usd)`. The single place provider
  usage flows into agent state.
- One accumulation point: `Agent.record_usage` adds
  `prompt_tokens`/`completion_tokens`/`cached_tokens` into per-agent
  accumulators and `cost_usd` into a running total. None-safe: a `None`
  usage or missing key contributes nothing.
- One read seam: `build_agent_tree` copies the accumulated usage into
  `AgentNode` (`tokens = prompt + completion`); `build_stats` aggregates the
  node values into `Stats`, so `stats.json` reports real totals.
- The mock path reports zeros: `MockDriver`/`MockLLM` never set usage, so
  `record_usage` is never called and the view-model renders zero defaults
  (`AgentNode.usage` renders the empty string).
- `cost_usd` is a provider estimate, not a billing figure; the view-model
  reports it as such.
- Open: whether `messages` (also inert) is populated from the same seam, and
  whether `context_tokens` derives from the digest size (`framework/context.py`,
  `DIGEST_KEEP`) or the provider's `prompt_tokens`. The seam is shaped so
  either can be added without a second write path.

## Owns
- The state view-model: what `ui/state.py` builds, the enum-driven terminal
  mapping, and the token/cost provenance seams (write, accumulate, read).

## Excludes
- The event-stream discipline that delivers events to the writer — `INFO-048`,
  `INFO-051`.
- The module layout that places the writer in `ui/` — `INFO-055`.
- The decisions that set the mapping and the seams — `IMD-002`, `IMD-003`.
