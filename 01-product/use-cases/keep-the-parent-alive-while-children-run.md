---
id: INFO-014
type: info
title: Keep the parent alive while children run
summary: A parent that spawned children stays alive until they settle, so channels stay open and it can receive results, escalations, and track child state
date: 2026-10-05
status: current
---

# Keep the parent alive while children run

- A parent that spawns children does not end when the spawning action returns; it stays alive until every child has settled — returned a result or a failed result (`INFO-005`).
- While alive, it receives what children send: point-to-point results (`INFO-009`), escalations (`INFO-011`), and summaries from re-decomposing grandchildren (`INFO-010`).
- It can track each child's state — running, done, or failed — because liveness is what makes every child-to-parent method deliverable.
- If the parent itself dies mid-supervision, the whole subtree it supervised fails with it and surfaces as one failed result to its own parent (`INFO-005`).

## Owns
- Parent liveness and supervision: the parent persists past its spawning action until its children settle, and tracks child states while they run.

## Excludes
- The per-agent turn loop this rides on — `INFO-002`.
- The spawning and decomposition contract itself — `INFO-004`.
- The communication patterns liveness enables: static fan-out — `INFO-009`, re-decomposition — `INFO-010`, escalation — `INFO-011`.
- Crash of the parent, which fails the supervised subtree — `INFO-005`.
