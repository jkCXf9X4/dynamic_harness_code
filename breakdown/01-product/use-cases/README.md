---
title: Use cases
summary: The use cases the dhc runtime commits to, extracted from the vision
---

# Use cases

How actors meet the dhc runtime: the action loop, V-model decomposition and self-verification, delegation, artifacts, and the container boundary. Facts here answer "what can a user of dhc do?"; each use case is one externally observable behavior. The `## Contents` groups the public interface: the operator, the runtime process itself, artifacts, the V-model, and the code interface — the harness's internal organization of delegation, peers, and own execution lives one layer down in Architecture.

## Owns
- The use-case-level capabilities of the runtime.

## Excludes
- Why these capabilities exist — `INFO-001`.
- Product-wide capability routing and boundaries.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- [Artifacts](artifacts/README.md) — The durable, content-addressed medium agents publish, consume, and trace
- [Capabilities and the primitive surface](capabilities/README.md) — Extending what agents can do, and the minimal execution-core contract behind it
- [Communication](communication/README.md) — How messages travel after spawn — await, poll, callbacks, completion scheduling, and settlement
- [Operator use cases](operator/README.md) — The operator converses with, steers, and observes the mesh through the root and the TUI
- [Peer exchange](peers/README.md) — Agents exchange work directly — sibling handoffs, direct messages, and shared rooms
- [Relationship](relationship/README.md) — The delegation structure — who spawns whom, the fan-out shapes, hierarchy setup, liveness and supervision, and the cancellation contract
- [Run the runtime](run-the-runtime/README.md) — Host, resume, and embed the runtime process as a whole, from outside the agent mesh
- [The V-model](vee_model/README.md) — Turn-as-code decomposition and self-verification — decompose recursively, self-verify each turn
<!-- pb:index:end -->
