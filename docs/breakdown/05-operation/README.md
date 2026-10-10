---
title: Operation
summary: Routine build, release, and run — how the dhc runtime is installed, started, and demonstrated
---

# Operation

Routine build, release, and run: how the product is installed, started, and demonstrated in normal operation. Facts here answer "how is it run day to day?"; how claims are checked lives one layer up in Verification, and the code layout lives two layers up in Implementation. The committed operation decisions live in the decision archive's index (`docs/archive/decisions/README.md`) — dated history, one choice per record.

## Owns
- How the product is built, installed, and run: the quick start, the entry points, and the demonstration scripts.
- Runbooks and routine maintenance.

## Excludes
- How claims are checked — one layer up in Verification.
- Why a file exists or how the parts fit — Architecture, two layers up.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-057** [Quick start](quick-start.md) — Install and run — mock path, real LLM path, and the end-to-end value demonstration
- **INFO-070** [The two entry points](the-two-entry-points.md) — The two CLI surfaces — the dhc chat command on a bare runtime and the operator terminal on a wired runtime — and what each constructs
- **INFO-071** [Operator runbook](operator-runbook.md) — Where run output lands and how to read it — state files, the boundary event log, artifact layout, chat context files, and resume
<!-- pb:index:end -->
