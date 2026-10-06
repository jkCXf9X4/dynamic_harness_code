---
title: Delegation
summary: A parent decomposes work, directs its children, and supervises them to settlement
---

# Delegation

How the harness organizes parent-to-child work: decomposition, fan-out,
escalation, containment, synchronization, and the setup of multi-level
organizations. The public-interface commitments these fulfill live one
layer up in Product.

## Owns
- Every parent-to-child behavior, including hierarchy setup.

## Excludes
- Peer-to-peer exchange without a parent mediating — `peers/`.
- One agent's own loop and state — `own-execution/`.

## Contents

<!-- pb:index:start -->
- **INFO-004** [Decompose a task recursively](decompose-a-task-recursively.md) — A parent writes delegation code that spawns encapsulated child workers and receives summaries plus artifact IDs
- **INFO-005** [Contain and surface a crashed child](contain-and-surface-a-crashed-child.md) — A crashed child is contained and never takes down siblings or the parent; it surfaces as a failed result
- **INFO-009** [Fan out for a complicated problem](fan-out-for-a-complicated-problem.md) — A parent decomposes once into known-shape subtasks, runs them in parallel, and aggregates point-to-point results
- **INFO-010** [Re-decompose from within a child](re-decompose-from-within-a-child.md) — A child that discovers its allocated requirement was under-scoped writes its own delegation code mid-task
- **INFO-011** [Escalate an unreachable requirement](escalate-an-unreachable-requirement.md) — A child whose acceptance criteria prove unreachable reports a failed result with a reason and the parent re-allocates
- **INFO-013** [Broadcast one requirement to many children](broadcast-one-requirement-to-many-children.md) — A parent spawns many children with the same requirement differing only in one parameter and picks among the results
- **INFO-014** [Keep the parent alive while children run](keep-the-parent-alive-while-children-run.md) — A parent that spawned children stays alive until they settle, so channels stay open and it can receive results, escalations, and track child state
- **INFO-018** [Set up a multi-level organization](set-up-a-multi-level-organization.md) — The root delegates to group leads and each lead delegates further, with the delegating parent assigning each group its own communication structure and children receiving exactly those channels
- **INFO-019** [Set up the whole hierarchy in one action](set-up-the-whole-hierarchy-in-one-action.md) — A single agent spawns every level of a hierarchy in one action and gives each middle agent its already-active subagents and a role message, while communication still routes through the parent chain
- **INFO-031** [Synchronize with a child on demand](synchronize-with-a-child-on-demand.md) — A parent blocks on await until a child reaches a terminal state — the fork/join pattern, composable with callbacks and polling
- **INFO-032** [Poll a child without blocking](poll-a-child-without-blocking.md) — A parent inspects a child's lifecycle state on demand — pending, running, completed, failed, cancelled, timeout — without synchronizing
- **INFO-033** [Run completion callbacks in the parent](run-completion-callbacks-in-the-parent.md) — A parent can register a callback that runs in its own REPL when a child settles — success or failure — never concurrently with parent code
- **INFO-034** [Cancel a running child](cancel-a-running-child.md) — A parent can cancel a child it no longer needs; the child settles as cancelled and the outcome surfaces like any terminal state
- **INFO-039** [Schedule child completions between parent actions](schedule-child-completions-between-parent-actions.md) — Child completions reach the parent as events and the parent's runtime dispatches callbacks between the parent's own actions
- **INFO-040** [Stop a cancelled child's worker](stop-a-cancelled-child-s-worker.md) — A parent's cancel request terminates the child's worker, and the child settles as cancelled with its partial work discarded
<!-- pb:index:end -->
