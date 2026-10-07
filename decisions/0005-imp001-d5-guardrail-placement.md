---
id: 0005
type: decision
title: "IMP-001 D5 — Guardrail placement: authored in the REPL, bound at spawn, enforced by the pump"
date: 2026-10-07
status: accepted
---

# D5 — Guardrail placement: authored in the REPL, bound at spawn, enforced by the pump

## Context

Guardrail policy is per-delegation (response policy is the parent's job,
excluded from INFO-021), but today there is no mechanism to inject *custom*
guardrails "from `execute(code)` → `spawn(...)`" — only a hard-coded rot
detector that logs and the one-size prompt. The scoping question is where
guardrails live: inside agent code, as static spawn params, or decomposed
across the REPL / pump / parent.

## Decision

Guardrails decompose into three layers:

- **(a) Normative** constraints the child should internalize — parent-imposed
  ones arrive as visible context-in at delegation (INFO-050); self-authored
  ones are ordinary workspace data.
- **(b) Operational** tripwires (rot threshold, budgets, forced compaction,
  termination) evaluated by the pump between steps and visible/editable to the
  agent except where they meet the ceiling caps (D2).
- **(c) Reactions** (terminate, re-decompose, signal parent) shipped as
  completion-style events on the parent's stream and executed in the parent's
  REPL — the INFO-033 / INFO-047 pattern.

The **pump, not agent code, owns enforcement timing**, so a degrading agent
cannot silently skip a tripwire at the ceiling.

## Rationale

The parent is the decomposition owner (INFO-004); its reaction must run in the
parent, never in the child — a child executing its own termination reaction is
a self-defeating leash. The pump owns enforcement timing so a degrading agent
cannot silently skip a tripwire at the ceiling. Normative constraints are
visible context-in so the child can internalize them; operational tripwires
are pump-evaluated so they bind even when the agent degrades; reactions ride
the existing completion/event machinery (INFO-033/INFO-047) so no new
transport is invented.

## Alternatives Considered

- **All guardrails inside agent code** — a degrading agent defeats its own
  leash. Rejected.
- **All guardrails at spawn as static params** — no evolution of policy
  mid-run, no custom hooks. Rejected.

## Consequences

- `runtime.py` `_pump_agent` evaluates operational tripwires between steps and
  enforces the ceiling caps; reactions are emitted as completion-style events
  on the parent's stream.
- The parent's REPL executes reactions (terminate, re-decompose, signal
  parent) — never the child's.
- Guardrail *content* and reaction policy semantics are excluded from this IMP
  (owned by the delegation contract INFO-004 and rot detection INFO-021 on
  adoption).
- INFO-021 is extended on adoption so rot response policy can ride the new
  guardrail/reaction surface instead of only logging.