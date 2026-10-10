---
id: INFO-047
type: info
title: Dispatch child completions between parent actions
summary: The runtime-owned queue and dispatcher carrying child completions to the parent — one event per settled child, callbacks between the parent's own actions
date: 2026-10-06
status: current
---

# Dispatch child completions between parent actions

- When a child settles, its completion enters the parent's channel as one event; the runtime queues it as it happens (`INFO-046`).
- The dispatcher runs the registered callback between the parent's own actions, in completion order — never concurrently with parent action code (`INFO-033`, `INFO-039`).
- Nested completions deliver the same way: a callback that needs another child's result spawns and awaits on its own, and those completions queue normally (`INFO-046`).

## Owns
- The completion-dispatch machinery: the runtime-owned queue and the inter-action dispatcher.

## Excludes
- The callback contract this dispatch delivers — `INFO-033`.
- The scheduling contract the parent observes — `INFO-039`.
- The settlement pattern — `INFO-046`.
- The stream resolution this dispatch completes — `INFO-048`.
