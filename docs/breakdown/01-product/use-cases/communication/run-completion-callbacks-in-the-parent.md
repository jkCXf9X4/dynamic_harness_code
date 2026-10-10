---
id: INFO-033
type: info
title: Run completion callbacks in the parent
summary: A parent can register a callback that runs in its own REPL when a child settles — success or failure — never concurrently with parent code
date: 2026-10-06
status: current
---

# Run completion callbacks in the parent

- **Completion callback on the child handle.**
  - Parent registers a completion callback against a spawned child's handle.
  - Callback runs when that child settles, success or failure alike.
- **Push side of synchronization** (`INFO-031`, `INFO-032`).
  - Parent does not block or poll.
  - The settled result comes to the parent.
  - Parent chooses per child: await, poll, or be notified.
- Execution stays in the parent's own REPL, never concurrently with parent code (`INFO-050`).
- The callback receives settled values, never stream handles (`INFO-051`).
- One callback per terminal: child settlement triggers its registered callback at most once (`INFO-046`).
- **Cancellation observes the same contract** (`INFO-034`).
  - Callback branches on `ok` and the reason.
  - Cancelled child reads like any other terminal.

## Owns
- **Completion-callback contract.**
  - Registration against a child handle.
  - Firing on settle, success or failure alike.
  - Execution in the parent's own REPL, never concurrently with parent code.
  - Settled values, not stream handles.
  - One callback per terminal.

## Excludes
- The REPL the callback executes in: the agent's single execution context — `INFO-050`.
- The event stream the settled values arrive on — `INFO-051`.
- When callbacks run relative to the parent's own actions, and in what order — `INFO-039`.
- The settlement discipline the callback participates in — `INFO-046`.
- The dispatch machinery carrying completions parent-ward — `INFO-047`.
- The await and poll primitives the callback composes with — `INFO-031`, `INFO-032`.
- Parent liveness while children run — `INFO-014`.
