---
title: Evolution
summary: Future work and risk — evidence-backed IMP candidates awaiting decision, adoption, or removal
---

# Evolution

Candidates for change, not current state: each IMP carries an evidence-backed
pain or risk and a scoped proposal. A candidate leaves this layer once its
resulting state is written into the owning layer, or when it is rejected.

## Owns
- Not-yet-decided improvement candidates (IMPs) and selected-but-not-implemented work.

## Excludes
- Current-state facts, which live in the owning layer's leaves.
- Dated rationale for committed choices, which lives in the decision stream.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- [Implemented IMPs](implemented/README.md) — Decided IMPs whose resulting state is written into the owning layer — historical record, no longer tracked as open work
- [Selected IMPs](selected/README.md) — Holding area for future IMP candidates — currently empty; scoped candidates land here before decision
<!-- pb:index:end -->

## Open IMPs

None. `selected/` is the holding area for future candidates; it is currently
empty.

## Decided

- **IMP-001** Agent-owned executor — the REPL as the main loop · decided · `TC-001` + `AD-001`–`AD-006`
- **IMP-002** Stringly-typed event kinds in the state snapshot · decided · `IMD-002`
- **IMP-003** Mixed wall-clock bases across caps, step start, and sleep deadline · decided · `AD-007`
- **IMP-004** Inert token and cost fields on the agent state view-model · decided · `IMD-003`
