---
id: INFO-018
type: info
title: Set up a multi-level organization
summary: The root delegates to group leads and each lead delegates further, with the delegating parent assigning each group its own communication structure and children receiving exactly those channels
date: 2026-10-05
status: current
---

# Set up a multi-level organization

- The root decomposes into group leads and each lead decomposes further into workers — the organization spans several levels, each delegated by the one above (`INFO-004`, `INFO-010`).
- The delegating parent assigns each group its own communication structure — fan-out only, a shared room, a handoff pipeline, peer links — and a child gets exactly the channels its group declares (`INFO-009`, `INFO-016`, `INFO-012`, `INFO-015`).
- Groups differ *within the same organization*: one group's siblings hand off directly while another group's may not. The structure is the parent's per-group choice, not a global rule.
- Cross-group contact happens only through what the parent wired — a designated liaison pair or a shared room; by default, agents of different groups cannot address each other.
- Escalation is not a group channel: any agent at any level escalates to its parent regardless of its group's structure (`INFO-011`).
- Supervision applies at every level: a lead keeps its workers alive the way the root keeps leads alive (`INFO-014`), and a lead's death fails its group the way a root's death fails the subtree (`INFO-005`).
- The organization's shape is itself observable — the operator sees the org structure through the same headline→summary→report tiers as any artifact (`INFO-006`, `INFO-017`).

## Owns
- Multi-level delegation with per-group communication structures: the parent chooses each group's channels, children receive exactly those, and cross-group contact only via wired links.

## Excludes
- Plain fan-out, the single-level delegation pattern — `INFO-009`.
- The individual channels themselves: sibling handoff — `INFO-012`, direct messaging — `INFO-015`, the shared room — `INFO-016`.
- Escalation and supervision mechanics — `INFO-011`, `INFO-014`, `INFO-005`; this leaf owns only their multi-level composition.
- Re-decomposition within one agent — `INFO-010`; a lead's re-decomposition happens inside the group structure it was given.
