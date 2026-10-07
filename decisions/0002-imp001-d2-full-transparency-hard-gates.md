---
id: 0002
type: decision
title: "IMP-001 D2 — Full transparency, bounded only by a hard-gate layer"
date: 2026-10-07
status: accepted
---

# D2 — Full transparency, bounded only by a hard-gate layer

## Context

The model's context is lossy and runtime-squeezed: `LLMDriver._build_prompt`
feeds the model only the agent's requirement, acceptance, status and the last
~5 events (`LLMDriver._recent_context`, `limit=5`, 200 chars each), and
`runtime.events` *drains* the stream — consumed events never come back. The
persistent REPL workspace (INFO-050), which actually accumulates the agent's
knowledge, is never summarized for the model. Any multi-turn agent is working
blind on its own history.

The scoping question is how much of its own workspace an agent may see and
edit: everything, or a layered digest.

## Decision

The agent sees and may edit **everything** in its own workspace — including
its budgets, tripwires, guardrails, and the loop itself — apart from **four
non-negotiable gates** that are not variables but pump behavior:

1. **Settlement at-most-once** (INFO-046) — a settled agent cannot be
   re-settled; the completion log is the single source of truth.
2. **Crash containment / blast radius** (INFO-005) — a broken loop costs one
   agent, not the mesh; failures are contained values.
3. **Outer ceiling caps** — wall-clock, step count, workspace size, child
   count, message rate — enforced by the pump, not by agent code.
4. **Cancellation grace** (INFO-040) — cancellation lands between steps; a
   generator that ignores cancellation is killed, rolled back, and settled.

Full transparency also kills the "injection channel" problem: there is no
separate channel for messages/guardrails/context because the agent *is* the
loop and reads/edits those as ordinary data.

## Rationale

Maximum autonomous experimentation is the point of the change; the gates
guarantee a hostile or degrading workspace cannot take down the mesh. The
gates are pump behavior, not variables, so a degrading agent cannot silently
edit its way out of them. Full transparency removes the runtime-squeezed read
model that is the root pain of the current design.

## Alternatives Considered

- **Layered visibility (normative open, operational digest)** — safer, but
  leaves a runtime-squeezed read model and re-creates an injection mechanism.
  Rejected in favor of transparency for this candidate.

## Consequences

- `operator.inspect(agent_id)` becomes a legitimate read-only window into a
  live workspace (full transparency makes it safe).
- The pump owns enforcement timing for the four gates; agent code cannot
  override them.
- Ceiling-cap defaults are added to `config.py` (wall-clock, steps, workspace
  bytes, children, messages).
- The hard-gate count stays exactly four for this IMP; whether it grows is an
  open question tracked in the IMP's risks.