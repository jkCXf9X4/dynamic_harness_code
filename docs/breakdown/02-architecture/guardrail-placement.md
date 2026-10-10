---
id: INFO-061
type: info
title: Guardrail placement
summary: The general three-part placement model for guardrails: normative (context-in), operational (pump-evaluated tripwires), reactions (executed in the parent's REPL)
date: 2026-10-09
status: current
---

# Guardrail placement

Guardrails decompose into three parts, each with a distinct home (`AD-005`):

- **Normative**:
  - Constraints the child should internalize.
  - Parent-imposed ones arrive as visible context-in at delegation (`INFO-050`).
  - Self-authored ones are ordinary workspace data.
- **Operational**:
  - Tripwires: rot threshold, budgets, forced compaction, termination.
  - Evaluated by the pump between steps.
  - Visible and editable to the agent except where they meet the ceiling caps (`AD-002`).
- **Reactions**:
  - Terminate, re-decompose, signal parent.
  - Shipped as completion-style events on the parent's stream.
  - Executed in the parent's REPL (`INFO-033` / `INFO-047`).

- Pump, not agent code, owns enforcement timing.
  - So a degrading agent cannot silently skip a tripwire at the ceiling.
- Parent, not child, owns reactions.
  - So a child never executes its own termination.

## Owns
- General three-part guardrail placement model: what each part is, where it lives.

## Excludes
- Control split separating agent from runtime: `INFO-053`.
- Rot detection and rot policy: `INFO-021`.
- Delegation contract owning reaction policy: `INFO-004`.
