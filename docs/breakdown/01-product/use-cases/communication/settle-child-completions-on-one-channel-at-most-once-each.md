---
id: INFO-046
type: info
title: Settle child completions on one channel, at most once each
summary: One settled child becomes one completion the parent receives — the callback gets settled values, at most once each, never concurrently
date: 2026-10-06
status: current
---

# Settle child completions on one channel, at most once each

- **One settled child = one completion the parent receives** (`INFO-039`).
  - The callback runs between the parent's own actions.
- **Callback input and execution** (`INFO-033`).
  - Callback receives settled values, never stream handles.
  - Execution stays in the parent's REPL, never concurrently with parent code.
- **Settlement is at most once each** (`INFO-051`).
  - Whichever consumer settles first wins.
  - The other consumer sees nothing.
- **Awaiting a child after its event settled still succeeds** (`INFO-031`).
  - Semantics: ensure-terminal, not first observation.
- **Settlement is flat.**
  - A callback cannot await.
  - One needing another child's result spawns and awaits on its own.
  - Those completions deliver the same way.
- **Cancellation settles like any terminal** (`INFO-034`).
  - The event reads like any other terminal event.
  - The callback branches on `ok` and the reason.

## Owns
- **The settlement contract.**
  - One settled child = one completion the parent receives.
  - The callback receives settled values, at most once each, never concurrently.

## Excludes
- The event stream as seen from agent code, and the machinery that resolves it — `INFO-051`, `INFO-048`.
- **Parent-side synchronization primitives: await and poll** (`INFO-031`, `INFO-032`).
  - The channel's pull side.
  - The callback receives settled values.
- **Where the callback runs, and the one-callback-per-terminal contract** (`INFO-033`).
  - The callback runs in the parent's own REPL.
  - One callback per terminal.
- **Where the events queue, and when the callback dispatches** (`INFO-039`, `INFO-047`).
  - Where the events queue.
  - When the callback dispatches.
- Parent liveness while children run — `INFO-014`.
