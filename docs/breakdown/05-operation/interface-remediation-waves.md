---
id: INFO-073
type: info
title: Interface remediation waves
summary: What the 2026-10 interface review found, what waves 0-7 changed, and the accepted deviations — pointers to the review and fix-plan documents
date: 2026-10-13
status: current
---

# Interface remediation waves

An interface review (2026-10) found the agent-facing and operator-facing
surfaces had drifted from their docs. A wave plan (W0–W7) landed it.
Source documents, kept at repo root as the historical record:

- `docs/interface-review.md` — the findings (F1-F10) and root causes.
- `docs/interface-fix-plan.md` — the wave plan (W0-W7) and acceptance criteria.

The fix-plan carries a finding→wave→success-criterion traceability table
and a per-wave definition of done; the review carries the severity table
the plan's F1–F10 labels refer to.

## What landed

- W0 — prompt↔API conformance test (`tests/llm/test_prompt_conformance.py`).
- W1 — the surface registry (`src/dhc/framework/surface.py`): every
  namespace name registered once with a tier; the prompt's API section is
  generated from it (`registry.prompt_section()`), not hand-written.
- W2 — onboarding truth: README links fixed, echo banner, portable
  `examples/value_demo.py`.
- W3 — agent API: `Message.id`, artifact coercion, `room_name`, `ack`,
  `answers`, `gather`, loud errors, `ask_operator` returns a qid.
- W4 — embedder hygiene: typed `WiredRuntime`, `UnknownAgentError`,
  `Agent.record_result`, public helpers (`agents_snapshot`,
  `is_stopped`, `caps_state`).
- W5 — config: `HarnessConfig` canonical, `Settings` a read-only view,
  `ALIASES` deprecation warnings, generated `harness.json.example`
  (`tools/generate_harness_example.py`), `--config` flag.
- W6 — operator UX: default `CheckpointStore` (`/resume` works out of the
  box), honest `!steer` (delivery reported truthfully), unknown-id
  messages, `ChatSession.COMMANDS` banner, `/q`, `--model` removed from
  chat, `--mock` documented no-op.
- W7 — generated docs: `docs/quickstart.md` (executed in CI),
  `docs/agent-api.md` (generated from the registry, freshness-guarded),
  README quick start ≤14 concepts, this truth pass.

## Accepted deviations

- `max_turn_seconds` stays a distinct per-step timeout (W5, deliberate):
  it is the step budget, not the LLM call timeout
  (`llm.call_timeout_seconds` is that one).
- `runtime.artifact_store_real` is deprecated, forwarding to
  `runtime.artifact_store` (the `StoreAdapter`, W4).
- `run_block` takes no `timeout` parameter (W4.4, truth-in-signatures):
  the outer step timeout is the only bound, and the fabrication kit's
  wrapper passes nothing through.

## Owns
- The summary of what the interface remediation changed and where the
  historical record lives.

## Excludes
- Per-finding evidence: the source documents themselves (the review's
  severity table, the fix-plan's traceability matrix and per-wave
  acceptance criteria).
- Current-state facts about each surface: the owning leaves
  (`INFO-064`, `INFO-065`, `INFO-070`, `INFO-071`).
