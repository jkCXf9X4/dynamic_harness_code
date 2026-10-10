---
id: INFO-014
type: info
title: Keep the parent alive while children run
summary: A parent that spawned children stays alive until they settle, so channels stay open and it can receive results, escalations, and track child state
date: 2026-10-05
status: current
---

# Keep the parent alive while children run

- **Parent outlives the spawning action** (`INFO-005`).
  - Parent does not end when the spawning action returns.
  - Parent stays alive until every child has settled.
  - Settled = returned a result or a failed result.
- **Reception while alive.**
  - Parent receives what children send.
  - Point-to-point results (`INFO-009`).
  - Escalations (`INFO-011`).
  - Summaries from re-decomposing grandchildren (`INFO-010`).
- **Child-state tracking** (`INFO-032`).
  - Parent tracks each child's lifecycle state: pending, running, completed, failed, cancelled, timeout.
  - Liveness makes every child-to-parent method deliverable.
- **Per-child synchronization choice.**
  - Block on await until terminal (`INFO-031`).
  - Poll without waiting (`INFO-032`).
  - Be notified by callback (`INFO-033`).
- **Parent death mid-supervision** (`INFO-005`).
  - The whole supervised subtree fails with it.
  - Surfaces as one failed result to its own parent.

## Owns
- **Parent liveness and supervision.**
  - Parent persists past its spawning action until its children settle.
  - Parent tracks child states while they run.

## Excludes
- The per-agent turn loop this rides on — `INFO-002`.
- The spawning and decomposition contract itself — `INFO-004`.
- **Communication patterns liveness enables.**
  - Static fan-out — `INFO-009`.
  - Re-decomposition — `INFO-010`.
  - Escalation — `INFO-011`.
  - Synchronization — `INFO-031`, `INFO-032`, `INFO-033`.
- Crash of the parent, which fails the supervised subtree — `INFO-005`.
