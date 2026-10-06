---
title: Communication
summary: How messages travel after spawn — await, poll, callbacks, completion dispatch, cancel delivery, and settlement
date: 2026-10-06
status: current
---

# Communication

## Owns
- How child completions travel parent-ward: the settlement channel and its consumers.

## Excludes
- The structure the messages travel through — `relationship/`.

## Contents

<!-- pb:index:start -->
- **INFO-011** [Escalate an unreachable requirement](escalate-an-unreachable-requirement.md) — A child whose acceptance criteria prove unreachable reports a failed result with a reason and the parent re-allocates
- **INFO-031** [Synchronize with a child on demand](synchronize-with-a-child-on-demand.md) — A parent blocks on await until a child reaches a terminal state — the fork/join pattern, composable with callbacks and polling
- **INFO-032** [Poll a child without blocking](poll-a-child-without-blocking.md) — A parent inspects a child's lifecycle state on demand — pending, running, completed, failed, cancelled, timeout — without synchronizing
- **INFO-033** [Run completion callbacks in the parent](run-completion-callbacks-in-the-parent.md) — A parent can register a callback that runs in its own REPL when a child settles — success or failure — never concurrently with parent code
- **INFO-039** [Schedule child completions between parent actions](schedule-child-completions-between-parent-actions.md) — Child completions reach the parent as events and the parent's runtime dispatches callbacks between the parent's own actions
- **INFO-040** [Stop a cancelled child's worker](stop-a-cancelled-child-s-worker.md) — A parent's cancel request terminates the child's worker, and the child settles as cancelled with its partial work discarded
- **INFO-046** [Settle child completions on one channel, at most once each](settle-child-completions-on-one-channel-at-most-once-each.md) — One settled child becomes one event on the parent's channel; the callback receives settled values — at most once each, never concurrently — while the runtime resolves the stream outside run_code
<!-- pb:index:end -->
