---
id: INFO-037
type: info
title: Commit to a minimal execution-core contract
summary: The execution behaviors lack a committed minimal contract; candidate: persistent REPL, non-blocking delegate, await/poll/callback/cancel, with observability at boundaries only
date: 2026-10-06
status: draft
---

# Commit to a minimal execution-core contract

- The pain: the execution behaviors are now committed piecemeal — persistent REPL (`INFO-030`), synchronization (`INFO-031`, `INFO-032`), callbacks (`INFO-033`), cancellation (`INFO-034`) — but nothing states the minimal contract that ties them together, or how it relates to the broader capability-surface candidate (`INFO-029`).
- The candidate: commit to a minimal execution-core contract with four concepts — REPL state (the persistent workspace), call (the synchronous execution boundary), task (asynchronous child execution), event (an externally observable lifecycle transition) — and the primitives call, delegate, await, status, on_done, cancel.
- The boundary property it commits to: the harness understands the lifecycle and the boundaries, not the internals of executed code — observability attaches at the boundaries only, keeping the action space unconstrained and the trace manageable.
- Relationship: complementary to `INFO-029` — that candidate proposes the full agent-facing capability surface; this one scopes the execution core inside it. Unifying the two is a later decision.
- Full analysis: `commit-to-a-minimal-execution-core-contract.analysis.md`, next to this leaf.

## Owns
- The execution-core-contract candidate: the minimal primitive set and its four-concept model.

## Excludes
- The broader capability-surface candidate — `INFO-029`.
- The individual behaviors the contract would tie together — `INFO-030`, `INFO-031`, `INFO-032`, `INFO-033`, `INFO-034`.
