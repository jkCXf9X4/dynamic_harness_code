---
id: INFO-039
type: info
title: Schedule child completions between parent actions
summary: Callbacks for settled children run between the parent's own actions, in completion order
date: 2026-10-06
status: current
---

# Schedule child completions between parent actions

- When a child settles, its registered callback runs between the parent's own actions.
- Callbacks run in completion order, not delegation order: children settle independently.

## Owns
- The inter-action scheduling contract: callbacks run between the parent's own actions, in completion order.

## Excludes
- The completion-callback contract this scheduling delivers — `INFO-033`.
- The dispatch machinery that carries completions between actions — `INFO-047`.
- The parent-side synchronization primitives, await and poll — `INFO-031`, `INFO-032`.
