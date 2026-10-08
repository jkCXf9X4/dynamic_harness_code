---
title: Selected IMPs
summary: Scoped candidates chosen for pursuit, awaiting decision records and adoption
---

# Selected IMPs

Candidates the product owner has picked and scoped. Ordering here is not a
schedule; adoption still runs through the change pipeline.

## Owns
- The selected-but-not-yet-adopted IMP queue.

## Excludes
- The pain and evidence behind each candidate, which lives in the IMP leaf.

## Contents

<!-- pb:index:start -->
- **IMP-002** [Stringly-typed event kinds in the state snapshot](stringly-typed-event-kinds-in-the-state-snapshot.md) — StateWriter matches event kinds by string literals instead of the EventKind enum, so a renamed or new kind silently drops from the snapshot
- **IMP-003** [Mixed wall-clock bases across caps, step start, and sleep deadline](mixed-wall-clock-bases-across-caps-step-start-and-sleep-deadline.md) — time.time and time.monotonic are mixed across the caps timeout, the step start, and the sleep deadline, so a wall-clock jump can trip or mask a cap
- **IMP-004** [Inert token and cost fields on the agent state view-model](inert-token-and-cost-fields-on-the-agent-state-view-model.md) — AgentNode's token and cost fields are never populated, so the state view-model reports zero usage even though the provider call already returns usage
<!-- pb:index:end -->
