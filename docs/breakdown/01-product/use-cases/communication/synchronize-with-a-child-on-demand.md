---
id: INFO-031
type: info
title: Synchronize with a child on demand
summary: A parent blocks on await until a child reaches a terminal state — the fork/join pattern, composable with callbacks and polling
date: 2026-10-06
status: current
---

# Synchronize with a child on demand

- Spawning is non-blocking: the delegation action returns a task handle immediately, and the parent continues (`INFO-009`).
- **Await blocks until terminal** (`INFO-009`).
  - Awaiting the handle blocks the parent until the child reaches a terminal state.
  - Basic fork/join pattern: fan out, run independently, join, synthesize.
- **Await is ensure-terminal, not first observation** (`INFO-033`).
  - A completion callback already processed the child's result.
  - Awaiting afterwards still succeeds.
- **Parent chooses per child when to synchronize** (`INFO-033`).
  - Immediately.
  - Only when the result becomes necessary.
  - Never: a callback instead.

## Owns
- **Await primitive semantics.**
  - Non-blocking spawn.
  - Blocking join.
  - Ensure-terminal, not first observation.

## Excludes
- Parent liveness while children run — `INFO-014`.
- The fan-out shape this composes into — `INFO-009`.
- Non-blocking inspection — `INFO-032`.
- Push-notification instead of blocking — `INFO-033`.
