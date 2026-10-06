---
id: INFO-033
type: info
title: Run completion callbacks in the parent
summary: A parent can register a callback that runs in its own REPL when a child settles — success or failure — never concurrently with parent code
date: 2026-10-06
status: current
---

# Run completion callbacks in the parent

- A parent can register a completion callback against a spawned child's handle; the callback runs when that child settles — success or failure alike.
- The callback is the push side of synchronization: the parent does not block or poll — the settled result comes to it, and the parent chooses per child whether to await, poll, or be notified (`INFO-031`, `INFO-032`).
- Execution stays in the parent's own REPL, never concurrently with parent code (`INFO-050`).
- The callback receives settled values, never stream handles (`INFO-051`).
- One callback per terminal: a child's settlement triggers its registered callback at most once (`INFO-046`).
- Cancellation observes the same contract: the callback branches on `ok` and the reason, so a cancelled child reads like any other terminal (`INFO-034`).

## Owns
- The completion-callback contract: registration against a child handle, firing on settle — success or failure — execution in the parent's own REPL never concurrently with parent code, settled values rather than stream handles, and one callback per terminal.

## Excludes
- The REPL the callback executes in — the agent's single execution context — `INFO-050`.
- The event stream the settled values arrive on — `INFO-051`.
- When callbacks run relative to the parent's own actions, and in what order — `INFO-039`.
- The settlement discipline the callback participates in — `INFO-046`.
- The dispatch machinery carrying completions parent-ward — `INFO-047`.
- The await and poll primitives the callback composes with — `INFO-031`, `INFO-032`.
- Parent liveness while children run — `INFO-014`.
