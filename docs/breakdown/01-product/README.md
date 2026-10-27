---
title: Product
summary: The promised deliverable — the externally observable behavior the dhc runtime commits to
---

# Product

The promised deliverable: the externally observable behavior the dhc runtime commits to its users and integrators. Facts here answer "what did we promise?"; scope and persona live one layer up in Intent, and how the promise is organized lives one layer down in Architecture.

## Owns
- Capabilities and requirements that others rely on.

## Excludes
- Why the product exists — `INFO-001`.
- How the parts fit and interact (Architecture).

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-053** [The control split — agent vs runtime](the-control-split-agent-vs-runtime.md) — Product-level control boundary: everything reachable in an agent workspace is the agent's to inspect and change. Every mesh-survival guarantee is runtime behavior no agent code can edit or skip.
- **INFO-054** [The core boundary — what the framework core knows](the-core-boundary-what-the-framework-core-knows.md) — Boundary orthogonal to the control split: framework core carries only what the control loop needs to be correct, plus the directed-message primitive. Everything that persists, observes, or renders state is operator tooling composed around it.
- **INFO-074** [Capabilities the framework enables, not performs](capabilities-the-framework-enables-not-performs.md) — Which scenario classes the framework supplies instruments for, and which workflow decisions stay with the agent
- [Use cases](use-cases/README.md) — The use cases the dhc runtime commits to, extracted from the vision
<!-- pb:index:end -->
