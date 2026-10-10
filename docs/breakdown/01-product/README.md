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
- **INFO-053** [The control split — agent vs runtime](the-control-split-agent-vs-runtime.md) — The product-level control boundary: everything reachable in an agent's workspace is the agent's to inspect and change; every mesh-survival guarantee is runtime behavior no agent code can edit or skip
- **INFO-054** [The core boundary — what the framework core knows](the-core-boundary-what-the-framework-core-knows.md) — The boundary orthogonal to the control split: the framework core carries only what the control loop needs to be correct plus the directed-message primitive; everything that persists, observes, or renders state is operator tooling composed around it
- [Use cases](use-cases/README.md) — The use cases the dhc runtime commits to, extracted from the vision
<!-- pb:index:end -->
