---
id: INFO-009
type: info
title: Fan out for a complicated problem
summary: A parent decomposes once into known-shape subtasks, runs them in parallel, and aggregates point-to-point results
date: 2026-10-05
status: current
---

# Fan out for a complicated problem

- **Known-shape subtasks** (`INFO-004`).
  - Complicated problem decomposes into known-shape subtasks.
  - Parent writes its delegation code once, before any child runs.
- **Child input and output** (`INFO-006`).
  - Each child receives its allocated requirement plus acceptance criteria.
  - Child answers point-to-point: one summary plus artifact IDs back to the parent.
- **Parallel, contained individually** (`INFO-005`).
  - Children run in parallel.
  - No child communicates with another child.
- **Non-blocking spawn.**
  - The delegation action returns task handles immediately.
  - Parent synchronizes later: await (`INFO-031`), polling (`INFO-032`), or callback (`INFO-033`).
- Parent aggregates child results into one artifact, returns it as its own result.
- Task tree is static: who-talks-to-whom is fixed at decomposition time.

## Owns
- Static fan-out delegation: point-to-point child reporting with parent-side aggregation.

## Excludes
- The general decomposition contract — `INFO-004`.
- In-task re-decomposition after children start — `INFO-010`.
- Peer-to-peer communication between children — `INFO-012`.
