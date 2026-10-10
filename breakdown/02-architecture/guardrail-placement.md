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

- **Normative** — constraints the child should internalize. Parent-imposed ones
  arrive as visible context-in at delegation (`INFO-050`); self-authored ones
  are ordinary workspace data.
- **Operational** — tripwires (rot threshold, budgets, forced compaction,
  termination) evaluated by the pump between steps; visible and editable to the
  agent except where they meet the ceiling caps (`AD-002`).
- **Reactions** — terminate, re-decompose, signal parent. Shipped as
  completion-style events on the parent's stream and executed in the parent's
  REPL (`INFO-033` / `INFO-047`).

The pump, not agent code, owns enforcement timing, so a degrading agent cannot
silently skip a tripwire at the ceiling. The parent, not the child, owns
reactions, so a child never executes its own termination.

## Owns
- The general three-part placement model for guardrails: what each part is and
  where it lives.

## Excludes
- The control split that separates agent from runtime — `INFO-053`.
- Rot detection and the rot policy — `INFO-021`.
- The delegation contract that owns reaction policy — `INFO-004`.
