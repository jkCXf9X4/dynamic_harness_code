---
id: INFO-034
type: info
title: Cancel a running child
summary: A parent can cancel a child it no longer needs; the child settles as cancelled and the outcome surfaces like any terminal state
date: 2026-10-06
status: current
---

# Cancel a running child

- **Parent cancels a child whose result it no longer needs** (`INFO-009`).
  - Example: one fan-out branch answered sufficiently.
  - The rest are stopped.
- **Parent-initiated cancellation.**
  - The child settles as cancelled.
  - The parent never receives its partial work.
- **Outcome surfaces like any terminal state.**
  - The completion event records cancelled.
  - Callbacks observe it (`INFO-033`).
  - The provenance trail shows it (`INFO-027`).
- Cancelling does not interrupt the parent: the parent keeps running (`INFO-014`).

## Owns
- Cancellation of a delegated child, and its surfacing as a terminal state.

## Excludes
- Child-initiated failure, which the child reports itself — `INFO-011`.
- Crash containment, which covers unplanned child death — `INFO-005`.
- The callback contract that observes the outcome — `INFO-033`.
- How cancellation is delivered to the child's worker — `INFO-040`.
