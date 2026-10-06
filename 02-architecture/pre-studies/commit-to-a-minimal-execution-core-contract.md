---
id: INFO-037
type: info
title: Commit to a minimal execution-core contract
summary: The execution behaviors lack a committed minimal contract; candidate: persistent REPL, non-blocking delegate, await/poll/callback/cancel, with observability at boundaries only
date: 2026-10-06
status: draft
---

# Commit to a minimal execution-core contract

- **The pain** — the execution behaviors are now committed piecemeal, but nothing states the minimal contract that ties them together:
  - Persistent REPL — `INFO-030`.
  - Synchronization — `INFO-031`, `INFO-032`.
  - Callbacks — `INFO-033`.
  - Cancellation — `INFO-034`.
  - Nothing states how the set relates to the broader capability-surface candidate (`INFO-029`).
- **The candidate** — commit to a minimal execution-core contract, with four concepts and their primitives:
  - REPL state — the persistent workspace.
  - Call — the synchronous execution boundary.
  - Task — asynchronous child execution.
  - Event — an externally observable lifecycle transition.
  - Primitives — `call`, `delegate`, `await`, `status`, `on_done`, `cancel`.
- **The boundary property** — the harness understands the lifecycle and the boundaries, not the internals of executed code:
  - Observability attaches at the boundaries only.
  - This keeps the action space unconstrained and the trace manageable.
- **Relationship** — complementary to `INFO-029`:
  - That candidate proposes the full agent-facing capability surface.
  - This one scopes the execution core inside it.
  - Unifying the two is a later decision.
- **Full analysis** — the `commit-to-a-minimal-execution-core-contract` sidecar, next to this leaf:
  - Its design model and recommended contract live one layer up in Architecture.

## Owns
- The execution-core-contract candidate: the minimal primitive set and its four-concept model.

## Excludes
- The broader capability-surface candidate — `INFO-029`.
- The individual behaviors the contract would tie together — `INFO-030`, `INFO-031`, `INFO-032`, `INFO-033`, `INFO-034`.
