---
title: Use cases
summary: The seven use cases the dhc runtime commits to, extracted from the vision
---

# Use cases

How actors meet the dhc runtime: the action loop, delegation, artifacts, and the container boundary. Facts here answer "what can a user of dhc do?"; each use case is one externally observable behavior.

## Owns
- The use-case-level capabilities of the runtime.

## Excludes
- Why these capabilities exist — `INFO-001`.
- Product-wide capability routing and boundaries.

## Contents

<!-- pb:index:start -->
- **INFO-002** [Run a coded action](run-a-coded-action.md) — A worker turn becomes one Python block the runtime persists and executes in a fresh subprocess
- **INFO-003** [Self-verify a turn](self-verify-a-turn.md) — Each action block analyzes its requirement, implements, verifies against the parents acceptance criteria, and reports
- **INFO-004** [Decompose a task recursively](decompose-a-task-recursively.md) — A parent writes delegation code that spawns encapsulated child workers and receives summaries plus artifact IDs
- **INFO-005** [Contain and surface a crashed child](contain-and-surface-a-crashed-child.md) — A crashed child stays contained in its own thread and surfaces as a failed result to its parent
- **INFO-006** [Publish and consume artifacts](publish-and-consume-artifacts.md) — Findings persist as immutable content-addressed artifacts that consumers pull headline-summary-report on demand
- **INFO-007** [Extend capabilities with agent tools](extend-capabilities-with-agent-tools.md) — Agents add capabilities outside the harness release cycle so the harness stays a substrate
- **INFO-008** [Host the runtime in a container](host-the-runtime-in-a-container.md) — An operator runs the dhc runtime inside Docker or Podman as the outer security boundary
- **INFO-009** [Fan out for a complicated problem](fan-out-for-a-complicated-problem.md) — A parent decomposes once into known-shape subtasks, runs them in parallel, and aggregates point-to-point results
- **INFO-010** [Re-decompose from within a child](re-decompose-from-within-a-child.md) — A child that discovers its allocated requirement was under-scoped writes its own delegation code mid-task
- **INFO-011** [Escalate an unreachable requirement](escalate-an-unreachable-requirement.md) — A child whose acceptance criteria prove unreachable reports a failed result with a reason and the parent re-allocates
- **INFO-012** [Hand off artifacts between siblings](hand-off-artifacts-between-siblings.md) — A sibling passes its published artifact directly to another sibling as input, without routing through the parent
- **INFO-013** [Broadcast one requirement to many children](broadcast-one-requirement-to-many-children.md) — A parent spawns many children with the same requirement differing only in one parameter and picks among the results
- **INFO-014** [Keep the parent alive while children run](keep-the-parent-alive-while-children-run.md) — A parent that spawned children stays alive until they settle, so channels stay open and it can receive results, escalations, and track child state
- **INFO-015** [Message another agent directly](message-another-agent-directly.md) — Any two agents can open a direct channel by identity and exchange request-reply traffic without a parent mediating
- **INFO-016** [Meet in a shared room](meet-in-a-shared-room.md) — Agents join a shared room where every posted message is visible to all members and any member can reply
- **INFO-017** [Converse with the operator](converse-with-the-operator.md) — The operator's request enters at the root agent and the root's result returns to the operator, the only door between human and mesh
<!-- pb:index:end -->
