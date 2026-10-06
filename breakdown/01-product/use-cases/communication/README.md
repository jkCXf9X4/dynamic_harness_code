---
title: Communication
summary: How messages travel after spawn — await, poll, callbacks, completion scheduling, and settlement
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
- **INFO-039** [Schedule child completions between parent actions](schedule-child-completions-between-parent-actions.md) — Callbacks for settled children run between the parent's own actions, in completion order
- **INFO-046** [Settle child completions on one channel, at most once each](settle-child-completions-on-one-channel-at-most-once-each.md) — One settled child becomes one completion the parent receives — the callback gets settled values, at most once each, never concurrently
<!-- pb:index:end -->
