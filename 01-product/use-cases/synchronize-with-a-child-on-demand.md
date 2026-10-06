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
- Awaiting the handle blocks the parent until the child reaches a terminal state — the basic fork/join pattern: fan out, run independently, join, synthesize (`INFO-009`).
- Awaiting is ensure-terminal, not first-observation: if a completion callback already processed the child's result, awaiting afterwards still succeeds (`INFO-033`).
- The parent chooses per child when to synchronize: immediately, only when the result becomes necessary, or never — a callback instead (`INFO-033`).

## Owns
- The await primitive's semantics: non-blocking spawn, blocking join, ensure-terminal-not-first-observation.

## Excludes
- Parent liveness while children run — `INFO-014`.
- The fan-out shape this composes into — `INFO-009`.
- Non-blocking inspection — `INFO-032`.
- Push-notification instead of blocking — `INFO-033`.
