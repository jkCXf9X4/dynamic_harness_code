---
id: INFO-040
type: info
title: Stop a cancelled child's worker
summary: A parent's cancel request terminates the child's worker, and the child settles as cancelled with its partial work discarded
date: 2026-10-06
status: current
---

# Stop a cancelled child's worker

- Cancellation is delivered by stopping the child's worker: the parent's cancel request terminates the worker, and the child settles as cancelled.
- The worker's partial work dies with it — it is never merged or delivered to the parent.

## Owns
- The cancellation-delivery design: a cancel request stops the child's worker and the child settles as cancelled.

## Excludes
- The cancellation contract this delivery implements — `INFO-034`.
- Crash containment, the unplanned-death counterpart — `INFO-005`.
