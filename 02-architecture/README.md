---
title: Architecture
summary: The organizing design — how the dhc runtime's parts fit and interact
---

# Architecture

The organizing design: how the dhc runtime's parts fit and interact. Facts here answer "how is the runtime organized?"; what the runtime promises lives one layer up in Product, and the concrete materialization lives one layer down in Implementation.

## Owns
- How the parts fit and interact: agent concurrency placement, completion dispatch, and cancellation delivery.

## Excludes
- What the runtime promises its users and integrators — one layer up in Product.
- Specific files, scripts, and configs — one layer down in Implementation.

## Contents

<!-- pb:index:start -->
- **INFO-038** [Run each agent in its own thread or process](run-each-agent-in-its-own-thread-or-process.md) — Every agent executes in its own thread-or-process unit, isolated from the runtime process and from every other agent
- **INFO-039** [Schedule child completions between parent actions](schedule-child-completions-between-parent-actions.md) — Child completions reach the parent as events and the parent's runtime dispatches callbacks between the parent's own actions
- **INFO-040** [Stop a cancelled child's worker](stop-a-cancelled-child-s-worker.md) — A parent's cancel request terminates the child's worker, and the child settles as cancelled with its partial work discarded
<!-- pb:index:end -->
