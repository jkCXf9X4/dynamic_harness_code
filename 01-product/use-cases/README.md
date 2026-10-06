---
title: Use cases
summary: The use cases the dhc runtime commits to, extracted from the vision
---

# Use cases

How actors meet the dhc runtime: the action loop, delegation, artifacts, and the container boundary. Facts here answer "what can a user of dhc do?"; each use case is one externally observable behavior. The `## Contents` groups the public interface: the operator, the runtime process itself, artifacts, and the code interface — the harness's internal organization of delegation, peers, and own execution lives one layer down in Architecture.

## Owns
- The use-case-level capabilities of the runtime.

## Excludes
- Why these capabilities exist — `INFO-001`.
- Product-wide capability routing and boundaries.

## Contents

<!-- pb:index:start -->
- [Artifacts](artifacts/README.md) — The durable, content-addressed medium agents publish, consume, and trace
- [Capabilities and the primitive surface](capabilities/README.md) — Extending what agents can do, and the minimal execution-core contract behind it
- [Operator use cases](operator/README.md) — The operator converses with, steers, and observes the mesh through the root and the TUI
- [Run the runtime](run-the-runtime/README.md) — Host, resume, and embed the runtime process as a whole, from outside the agent mesh
<!-- pb:index:end -->
