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
<!-- pb:index:end -->
