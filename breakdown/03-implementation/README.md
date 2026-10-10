---
title: Implementation
summary: The concrete materialization — files, modules, and code layout of the dhc runtime
---

# Implementation

The concrete materialization: files, modules, and code layout. Facts here answer "where is it, and what is in it?"; how the parts fit and interact lives one layer up in Architecture, and how claims are checked lives one layer down in Verification. The committed implementation decisions live in the decision archive's index (`docs/archive/decisions/README.md`) — dated history, one choice per record.

## Owns
- Modules, files, and the code layout: what each module owns, where each surface lives, and the package structure.
- Concrete code-level facts: a script's input and output contract, a config's knobs, a module's public names.

## Excludes
- How the parts fit and interact — one layer up in Architecture.
- What the runtime promises its users and integrators — two layers up in Product.
- How claims are checked — one layer down in Verification.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-055** [Module map](module-map.md) — What each module owns - the layout is the architecture
- **INFO-059** [State view model](state-view-model.md) — The operator's state view-model — what ui/state.py builds from the runtime, the enum-driven event-kind mapping, and the token/cost provenance seams that feed it
<!-- pb:index:end -->
