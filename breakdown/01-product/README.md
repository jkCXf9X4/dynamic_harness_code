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
- **INFO-053** [The control split — agent vs runtime](the-control-split-agent-vs-runtime.md) — The product-level control boundary: everything reachable in an agent's workspace is the agent's to inspect and change; every mesh-survival guarantee is runtime behavior no agent code can edit or skip
- [Use cases](use-cases/README.md) — The use cases the dhc runtime commits to, extracted from the vision
<!-- pb:index:end -->
