---
id: INFO-032
type: info
title: Poll a child without blocking
summary: A parent inspects a child's lifecycle state on demand — pending, running, completed, failed, cancelled, timeout — without synchronizing
date: 2026-10-06
status: current
---

# Poll a child without blocking

- Parent inspects child state without waiting: polling returns immediately with the current lifecycle state.
- **Lifecycle states** (`INFO-005`).
  - Pending, running, completed, failed, cancelled, timeout.
  - Terminal states are distinguishable, not a generic error.
- **Opportunistic use.**
  - Act on a finished child's result when one is ready.
  - Keep working when none is ready.
- Same states appear in the parent-facing result and the provenance trail, so observation and triage agree (`INFO-027`).

## Owns
- The child lifecycle-state vocabulary and the non-blocking poll primitive.

## Excludes
- Blocking synchronization — `INFO-031`.
- Completion callbacks, which push notification instead of pulling — `INFO-033`.
- The provenance trail that records the same transitions — `INFO-027`.
