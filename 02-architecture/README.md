---
title: Architecture
summary: The organizing design — how the dhc runtime's parts fit and interact
---

# Architecture

The organizing design: how the dhc runtime's parts fit and interact. Facts here answer "how is the runtime organized?"; what the runtime promises lives one layer up in Product, and the concrete materialization lives one layer down in Implementation. The `## Contents` groups the harness's internal organization: how parents delegate, how peers exchange, and how one agent's own execution runs — the public-interface commitments live one layer up in Product.

## Owns
- How the parts fit and interact: agent concurrency placement, completion dispatch, and cancellation delivery.
- How the harness organizes work: delegation from parents, peer exchange, and each agent's own execution — the three groups below.

## Excludes
- What the runtime promises its users and integrators — one layer up in Product.
- Specific files, scripts, and configs — one layer down in Implementation.

## Contents

<!-- pb:index:start -->
- [Delegation](delegation/README.md) — A parent decomposes work, directs its children, and supervises them to settlement
- **INFO-042** [Harness design model](harness-design-model.md) — The harness runs the code runtime as a black box — traceability attaches at the call-code and delegation boundaries only — giving the agent a highly expressive action space with observable, attributable boundaries
- **INFO-043** [Recommended minimal harness contract](recommended-minimal-harness-contract.md) — The entire model stays small — call_code, delegate, await, status, cancel — with four concepts (REPL state, call, task, event) and five events (CALL, DELEGATE, COMPLETE, AWAIT, CALLBACK), enough to answer what was asked, returned, spawned, and observed
- [Own execution](own-execution/README.md) — One agent's own action loop, verification, resilience, and persistent state
- [Peer exchange](peers/README.md) — Agents exchange work directly — sibling handoffs, direct messages, and shared rooms
<!-- pb:index:end -->
