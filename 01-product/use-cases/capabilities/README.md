---
title: Capabilities and the primitive surface
summary: Extending what agents can do, and the minimal execution-core contract behind it
---

# Capabilities and the primitive surface

Use cases about the capability surface itself: how agents extend it and what
minimal primitive contract it commits to.

## Owns
- The capability surface as a product commitment.

## Excludes
- The individual use cases that surface fulfills — the other groups.

## Contents

<!-- pb:index:start -->
- **INFO-007** [Extend capabilities with agent tools](extend-capabilities-with-agent-tools.md) — Agents add capabilities outside the harness release cycle so the harness stays a substrate
- **INFO-037** [Commit to a minimal execution-core contract](commit-to-a-minimal-execution-core-contract.md) — The execution behaviors lack a committed minimal contract; candidate: persistent REPL, non-blocking delegate, await/poll/callback/cancel, with observability at boundaries only
- **INFO-041** [Keep the code interface public and decoupled](keep-the-code-interface-public-and-decoupled.md) — The in-code capability surface counts as public interface, so it stays decoupled from the harness and can be developed as a separate entity
- [commit-to-a-minimal-execution-core-contract.analysis](commit-to-a-minimal-execution-core-contract.analysis.md)
<!-- pb:index:end -->
