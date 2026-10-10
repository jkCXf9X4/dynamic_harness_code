---
title: Verification
summary: Proof and acceptance — how the dhc runtime's claims are checked
---

# Verification

Proof and acceptance: how each claim is checked. Facts here answer "how do we know it is true?"; the thing under test lives in its owning layer, and routine build and run steps live one layer down in Operation. The committed verification decisions live in the decision archive's index (`docs/archive/decisions/README.md`) — dated history, one choice per record.

## Owns
- How claims are checked: the test strategy, the suite's shape, and the evidence that a claim holds.
- Acceptance criteria and the acceptance fixtures that prove them.

## Excludes
- The thing under test — its owning layer (Intent, Product, Architecture, Implementation).
- Routine build and run steps — one layer down in Operation.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-056** [Running the tests](running-the-tests.md) — How the suite is run — pytest commands, the deterministic MockDriver, and where the detail lives
- **INFO-067** [Test strategy](test-strategy.md) — What the test suite verifies and how — mirrored unit tests, the framework-tooling import boundary guard, integration through build_runtime, and top-level acceptance
- **INFO-068** [Acceptance criteria](acceptance-criteria.md) — The end-to-end criteria the kernel contract must satisfy — the D1 to D5 gates exercised by the acceptance suite
- **INFO-069** [The benchmark harness](the-benchmark-harness.md) — Ground-truth benchmark tasks with verifiable outcomes, per-run isolation, derived structural metrics, and the weighted scoring rubric
<!-- pb:index:end -->
