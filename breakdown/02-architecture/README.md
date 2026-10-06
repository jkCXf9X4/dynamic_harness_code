---
title: Architecture
summary: The organizing design — how the dhc runtime's parts fit and interact
---

# Architecture

The organizing design: how the dhc runtime's parts fit and interact. Facts here answer "how is the runtime organized?"; what the runtime promises lives one layer up in Product, and the concrete materialization lives one layer down in Implementation. The committed architecture decisions live in `decisions/README.md` — dated history, one choice per record. The `## Contents` groups the harness's internal organization: how parents delegate, how peers exchange, and how one agent's own execution runs — the public-interface commitments live one layer up in Product.

## Owns
- How the parts fit and interact: agent concurrency placement, completion dispatch, and cancellation delivery.
- How the harness organizes work: delegation from parents, peer exchange, and each agent's own execution — the three groups below.

## Excludes
- What the runtime promises its users and integrators — one layer up in Product.
- Specific files, scripts, and configs — one layer down in Implementation.

## Contents

<!-- pb:index:start -->

<!-- pb:index:end -->
