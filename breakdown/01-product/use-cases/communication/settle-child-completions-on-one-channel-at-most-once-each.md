---
id: INFO-046
type: info
title: Settle child completions on one channel, at most once each
summary: One settled child becomes one completion the parent receives — the callback gets settled values, at most once each, never concurrently
date: 2026-10-06
status: current
---

# Settle child completions on one channel, at most once each

- One settled child = one completion the parent receives; the callback runs between the parent's own actions (`INFO-039`).
- The callback receives settled values, never stream handles; execution stays in the parent's REPL, never concurrently with parent code (`INFO-033`).
- Settlement is at most once each — whichever consumer settles first wins, and the other sees nothing (`INFO-045`).
- Awaiting a child after its event settled still succeeds — ensure-terminal, not first observation (`INFO-031`).
- Settlement is flat: a callback cannot await; one that needs another child's result spawns and awaits on its own, and those completions deliver the same way.
- Cancellation settles like any terminal — the event reads like any other, the callback branches on `ok` and the reason (`INFO-034`).

## Owns
- The settlement contract: one settled child = one completion the parent receives; the callback receives settled values — at most once each, never concurrently.

## Excludes
- The event-stream boundary and the machinery that resolves it — `INFO-045`, `INFO-048`.
- The parent-side synchronization primitives, await and poll — `INFO-031`, `INFO-032` — the channel's pull side; the callback receives settled values.
- Where the callback runs — the parent's own REPL — and the one-callback-per-terminal contract — `INFO-033`.
- Where the events queue and when the callback dispatches — `INFO-039`, `INFO-047`.
- Parent liveness while children run — `INFO-014`.
