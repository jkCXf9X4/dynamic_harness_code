---
title: Implemented IMPs
summary: Decided IMPs whose resulting state is written into the owning layer — historical record, no longer tracked as open work
---

# Implemented IMPs

IMPs whose resulting state is written into the owning layer. Each is a
historical record of what was scoped and done; it is no longer tracked as open
work.

## Owns
- The historical record of implemented IMPs and the decision records that decided them.

## Excludes
- The current-state facts the IMPs produced, which live in the owning layer's leaves.
- The dated rationale, which lives in the decision stream.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **IMP-001** [Agent-owned executor — the REPL as the main loop](agent-owned-executor-the-repl-as-the-main-loop.md) — Workspace-owned resumable generator replaces the runtime's fixed loop — the agent authors and pumps it under a small hard-gate layer; full transparency for context, guardrails, and experimentation; mesh stays up
- **IMP-002** [Stringly-typed event kinds in the state snapshot](stringly-typed-event-kinds-in-the-state-snapshot.md) — StateWriter matches event kinds by string literals, not the EventKind enum. Renamed or new kind silently drops from the snapshot
- **IMP-003** [Mixed wall-clock bases across caps, step start, and sleep deadline](mixed-wall-clock-bases-across-caps-step-start-and-sleep-deadline.md) — time.time and time.monotonic mix across the caps timeout, the step start, and the sleep deadline. A wall-clock jump can trip or mask a cap
- **IMP-004** [Inert token and cost fields on the agent state view-model](inert-token-and-cost-fields-on-the-agent-state-view-model.md) — AgentNode's token and cost fields are never populated. State view-model reports zero usage; the provider call already returns usage
- **IMP-031** [run_code snippet format](run-code-snippet-format.md) — run_block accepts only def call(self, spec) payloads, validated and invoked with the agent facade; exec_block is the raw runner path
<!-- pb:index:end -->

## Decision records

- **IMP-001** — `imp001-adopted-task-contract` + `AD-001`–`AD-006`
- **IMP-002** — `IMD-002`
- **IMP-003** — `AD-007`
- **IMP-004** — `IMD-003`
