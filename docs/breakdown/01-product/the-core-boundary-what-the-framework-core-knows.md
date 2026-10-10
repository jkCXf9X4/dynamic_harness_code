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

- **Core scope.** The core owns only what the control loop needs to be correct: the guarantees listed under runtime control in `INFO-053`.
  - The control loop means the pump and the machinery that runs between agent actions (`AD-011`).
  - Core scope tracks that list by reference: editing `INFO-053`'s runtime list is a core-boundary change. Revisit this leaf when that list changes.
- **Runtime vs core.** The wired runtime is the core plus composed tooling (`INFO-058`).
  - The core enforces the `INFO-053` runtime guarantees; tooling carries their media.
  - Event discipline is core; the boundary log that persists the events is tooling.
- **Directed-message primitive.** `Runtime.send` emits a receiver-addressed `message_sent` event on the recipient's own stream (`AD-009`).
  - A direct message is guaranteed to reach the recipient's awareness: digest, recent context, `events` tool.
  - No channel is installed.
  - The use case: `INFO-015`.
- **Operator tooling.** Everything that persists, observes, or renders state is operator tooling: the artifact store, the boundary log, operator viewers.
  - Since `AD-009`, every communication *policy* is operator tooling: rooms, escalation routing, operator questions, the inbox read-state view.
  - Composed at the composition root.
  - One-way dependent on the core.
  - Removable without changing what the core guarantees.
- **Agent side.** Beyond the primitive, the agent's communication is its own choice: use, replace, or ignore each channel (`AD-009`).
- **Removability.** Removability is the entry condition for composition, not the verdict: removable does not mean tooling.
  - The REPL engine is removable and framework; the core operates it: install, advance, inject, kill (`AD-011`).
- **Classifier.** The classifier is what the core does with the concern.
  - Data the core only carries opaquely, so someone can persist, observe, or render it: tooling.
  - Semantics the core interprets, or the directed-message relay itself: framework.
- **Worked example: rot detection (`INFO-021`).**
  - Framework: the pump-side tripwire and policy semantics; the core interprets the report.
  - Composed: the scoring detector lives with the LLM driver (`dhc.llm`), attached at the composition root.
- **Worked example: artifact contract.**
  - Its *vocabulary* is framework: the content-addressed `Artifact` model, the disclosure tiers, the `artifact_published` event.
  - Its *medium* is tooling: the store holding the bodies.
- **Worked example: agent loop.** The agent loop is the third.
  - Framework: the pump, the runner contract, the yield vocabulary.
  - Runner contract covers compile, install, re-install, re-seed.
  - Tooling: the default agent, the fabrication kit a workspace is born with (`INFO-050`). Default `__runner__` and `decide` included.
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
- **The direct-messaging use case.** `INFO-015`.
- **How the boundary is implemented.** The architecture layer.
