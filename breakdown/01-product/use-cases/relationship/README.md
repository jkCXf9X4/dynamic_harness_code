---
title: Relationship
summary: The delegation structure — who spawns whom, the fan-out shapes, hierarchy setup, liveness and supervision, and the cancellation contract
---

# Relationship

## Owns
- The parent-child structure: fan-out shapes (`INFO-009`, `INFO-013`), hierarchy setup (`INFO-018`, `INFO-019`), in-task re-decomposition (`INFO-010`), liveness and supervision (`INFO-014`, `INFO-005`), and the cancellation contract (`INFO-034`).

## Excludes
- How results, escalations, and cancellations travel after spawn — `communication/`.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-005** [Contain and surface a crashed child](contain-and-surface-a-crashed-child.md) — A crashed child is contained and never takes down siblings or the parent; it surfaces as a failed result
- **INFO-009** [Fan out for a complicated problem](fan-out-for-a-complicated-problem.md) — A parent decomposes once into known-shape subtasks, runs them in parallel, and aggregates point-to-point results
- **INFO-010** [Re-decompose from within a child](re-decompose-from-within-a-child.md) — A child that discovers its allocated requirement was under-scoped writes its own delegation code mid-task
- **INFO-013** [Broadcast one requirement to many children](broadcast-one-requirement-to-many-children.md) — A parent spawns many children with the same requirement differing only in one parameter and picks among the results
- **INFO-014** [Keep the parent alive while children run](keep-the-parent-alive-while-children-run.md) — A parent that spawned children stays alive until they settle, so channels stay open and it can receive results, escalations, and track child state
- **INFO-018** [Set up a multi-level organization](set-up-a-multi-level-organization.md) — The root delegates to group leads and each lead delegates further, with the delegating parent assigning each group its own communication structure and children receiving exactly those channels
- **INFO-019** [Set up the whole hierarchy in one action](set-up-the-whole-hierarchy-in-one-action.md) — A single agent spawns every level of a hierarchy in one action and gives each middle agent its already-active subagents and a role message, while communication still routes through the parent chain
- **INFO-034** [Cancel a running child](cancel-a-running-child.md) — A parent can cancel a child it no longer needs; the child settles as cancelled and the outcome surfaces like any terminal state
<!-- pb:index:end -->
