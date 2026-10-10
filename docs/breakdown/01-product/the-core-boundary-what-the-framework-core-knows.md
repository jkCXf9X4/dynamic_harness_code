---
id: INFO-054
type: info
title: The core boundary — what the framework core knows
summary: Boundary orthogonal to the control split: framework core carries only what the control loop needs to be correct, plus the directed-message primitive. Everything that persists, observes, or renders state is operator tooling composed around it.
date: 2026-10-09
status: current
---

# The core boundary — what the framework core knows

The control split (`INFO-053`) answers **who enforces** (agent vs runtime).
This boundary is orthogonal to it, fixed by `AD-008`, refined by `AD-009`: **what the framework core carries**.

- **Core scope.** The core owns only what the control loop needs to be correct: the guarantees listed under runtime control in `INFO-053`, plus the directed-message primitive.
- **Directed-message primitive.** `Runtime.send` emits a receiver-addressed `message_sent` event on the recipient's own stream.
  - A direct message is guaranteed to reach the recipient's awareness: digest, recent context, `events` tool.
  - No channel is installed.
- **Operator tooling.** Everything that persists, observes, or renders state is operator tooling: the artifact store, the boundary log, operator viewers.
  - Since `AD-009`, every communication *policy* is operator tooling: rooms, escalation routing, operator questions, the inbox read-state view.
  - Composed at the composition root.
  - One-way dependent on the core.
  - Removable without changing what the core guarantees.
- **Agent side.** The agent's communication beyond the primitive is its own composition choice.
- **Removability.** Removability is the entry condition for composition, not the verdict.
  - The engine is removable and framework.
- **Classifier.** The classifier is what the core does with the concern.
  - Data the core only carries opaquely, so someone can persist, observe, or render it: tooling.
  - Semantics the core interprets, or the directed-message relay itself: framework.
- **Worked example: artifact contract.**
  - Its *vocabulary* is framework: the content-addressed `Artifact` model, the disclosure tiers, the `artifact_published` event.
  - Its *medium* is tooling: the store holding the bodies.
- **Worked example: agent loop.** The agent loop is the second.
  - Framework: the pump, the runner contract, the yield vocabulary.
  - Runner contract covers compile, install, re-install, re-seed.
  - Tooling: the default agent, the fabrication kit a workspace is born with. Default `__runner__` and `decide` included.
  - Composed tooling lives at `dhc.tooling.fabrication`.
  - Handed in via `Runtime(kit_factory=...)` at the composition root (`AD-011`).
  - The runtime guarantees a loop exists and enforces around it.
  - What the loop does is the agent's.

## Owns

- **Framework/tooling boundary.**
  - What the framework core carries versus the operator tooling composed around it.
  - The classifier that separates them.

## Excludes

- **The control split this boundary is orthogonal to.** `INFO-053`.
- **How the boundary is implemented.** The architecture layer.
