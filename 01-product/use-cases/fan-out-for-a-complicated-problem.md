---
id: INFO-009
type: info
title: Fan out for a complicated problem
summary: A parent decomposes once into known-shape subtasks, runs them in parallel, and aggregates point-to-point results
date: 2026-10-05
status: current
---

# Fan out for a complicated problem

- A complicated problem decomposes into known-shape subtasks, so the parent writes its delegation code once, before any child runs (`INFO-004`).
- Each child receives its allocated requirement plus acceptance criteria and answers point-to-point: one summary plus artifact IDs back to the parent (`INFO-006`).
- Children run in parallel and are contained individually (`INFO-005`); no child communicates with another child.
- Spawning is non-blocking: the delegation action returns task handles immediately; the parent synchronizes later — on await (`INFO-031`), by polling (`INFO-032`), or by callback (`INFO-033`).
- The parent aggregates the child results into one artifact and returns it as its own result.
- The task tree is static: who-talks-to-whom is fixed at decomposition time.

## Owns
- Static fan-out delegation: point-to-point child reporting with parent-side aggregation.

## Excludes
- The general decomposition contract — `INFO-004`.
- In-task re-decomposition after children start — `INFO-010`.
- Peer-to-peer communication between children — `INFO-012`.
