---
id: INFO-033
type: info
title: Run completion callbacks in the parent
summary: A parent can register a callback that runs in its own REPL when a child settles — success or failure — never concurrently with parent code
date: 2026-10-06
status: current
---

# Run completion callbacks in the parent

- Delegation accepts an optional completion callback; when the child reaches a terminal state, the callback runs in the parent's REPL.
- The callback never executes concurrently against the parent's workspace — the parent's REPL is never concurrently mutated.
- One callback serves success and failure: it receives the terminal state and the result or error, so no separate error-callback mechanism is needed.
- Multiple children notify independently; the parent observes each result as it becomes available.
- A callback may process a child's result before the parent explicitly awaits it; awaiting afterwards still succeeds — it ensures terminal state, not first observation (`INFO-031`).

## Owns
- The completion-callback contract: scheduling into the parent REPL, failure coverage, and independence across children.

## Excludes
- The await primitive — `INFO-031`.
- Non-blocking polling — `INFO-032`.
- Cancellation, which produces a terminal state callbacks can observe — `INFO-034`.
