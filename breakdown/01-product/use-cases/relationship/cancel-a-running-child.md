---
id: INFO-034
type: info
title: Cancel a running child
summary: A parent can cancel a child it no longer needs; the child settles as cancelled and the outcome surfaces like any terminal state
date: 2026-10-06
status: current
---

# Cancel a running child

- The parent can cancel a child whose result it no longer needs — for example, one fan-out branch answered sufficiently, so the rest are stopped (`INFO-009`).
- Cancellation is parent-initiated: the child settles as cancelled, and the parent never receives its partial work.
- The outcome surfaces like any terminal state: the completion event records cancelled, callbacks observe it (`INFO-033`), and the provenance trail shows it (`INFO-027`).
- Cancelling does not interrupt the parent: it keeps running (`INFO-014`).

## Owns
- Cancellation of a delegated child and its surfacing as a terminal state.

## Excludes
- Child-initiated failure, which the child reports itself — `INFO-011`.
- Crash containment, which covers unplanned child death — `INFO-005`.
- The callback contract that observes the outcome — `INFO-033`.
- How cancellation is delivered to the child's worker — `INFO-040`.
