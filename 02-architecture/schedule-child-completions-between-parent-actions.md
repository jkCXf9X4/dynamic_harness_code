---
id: INFO-039
type: info
title: Schedule child completions between parent actions
summary: Child completions reach the parent as events and the parent's runtime dispatches callbacks between the parent's own actions
date: 2026-10-06
status: current
---

# Schedule child completions between parent actions

- When a child settles, its completion reaches the parent as an event; the parent's runtime queues it and dispatches the registered callback between the parent's own actions.
- Callbacks run in completion order, not delegation order: children notify independently as they settle.

## Owns
- The completion-dispatch design: child completions queue as they happen; callbacks dispatch between parent actions.

## Excludes
- The completion-callback contract this dispatch delivers — `INFO-033`.
- The parent-side synchronization primitives, await and poll — `INFO-031`, `INFO-032`.
