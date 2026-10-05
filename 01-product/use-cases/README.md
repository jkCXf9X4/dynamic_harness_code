---
title: Use cases
summary: The use cases the dhc runtime commits to, extracted from the vision
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
- **INFO-018** [Set up a multi-level organization](set-up-a-multi-level-organization.md) — The root delegates to group leads and each lead delegates further, with the delegating parent assigning each group its own communication structure and children receiving exactly those channels
- **INFO-019** [Set up the whole hierarchy in one action](set-up-the-whole-hierarchy-in-one-action.md) — A single agent spawns every level of a hierarchy in one action and gives each middle agent its already-active subagents and a role message, while communication still routes through the parent chain
- **INFO-020** [Survive an LLM call timing out or terminating](survive-an-llm-call-timing-out-or-terminating.md) — A timed-out or terminated LLM call fails the turn safely and surfaces as a failed result instead of hanging or crashing the agent
- **INFO-021** [Detect context rot in an agent's output](detect-context-rot-in-an-agent-s-output.md) — The runtime detects degradation signatures such as repeating loops and gibberish in an agent's output stream and surfaces them to the parent
- **INFO-022** [Chat continuously while subagents run](chat-continuously-while-subagents-run.md) — Operator messages keep flowing while subagents run, and a message sent mid-turn steers the root's current turn immediately
- **INFO-023** [Ask the operator a question](ask-the-operator-a-question.md) — Any agent can ask the operator a question; the question routes up the parent chain and the answer returns to the asking agent
- **INFO-028** [Drive the TUI from persistent files](drive-the-tui-from-persistent-files.md) — The operator's TUI is a minimal chat whose content and layout are read from persistent files rather than hardcoded into the interface
<!-- pb:index:end -->
