---
id: INFO-010
type: info
title: Re-decompose from within a child
summary: A child that discovers its allocated requirement was under-scoped writes its own delegation code mid-task
date: 2026-10-05
status: current
---

# Re-decompose from within a child

- For a complex problem, the subtask shape is not knowable up front, so a child that discovers its allocated requirement was under-scoped writes its own delegation code mid-task (`INFO-004`).
- The child becomes a parent for its grandchildren, with the same encapsulated context contract one level deeper (`INFO-004`).
- The original parent only sees the child's summary and artifact IDs; the grandchild tree stays invisible to it.
- Depth is unbounded in principle: every agent, at any level, runs the same action model (`INFO-002`).

## Owns
- Child-initiated, in-task re-decomposition beyond one delegation hop.

## Excludes
- The decomposition contract this extends — `INFO-004`.
- Pre-execution fan-out with a fixed tree — `INFO-009`.
- Escalation instead of re-decomposition — `INFO-011`.
