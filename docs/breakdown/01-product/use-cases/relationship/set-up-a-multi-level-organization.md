---
id: INFO-018
type: info
title: Set up a multi-level organization
summary: The root delegates to group leads and each lead delegates further, with the delegating parent assigning each group its own communication structure and children receiving exactly those channels
date: 2026-10-05
status: current
---

# Set up a multi-level organization

- **Multi-level delegation** (`INFO-004`, `INFO-010`).
  - The root decomposes into group leads.
  - Each lead decomposes further into workers.
  - The organization spans several levels, each delegated by the one above.
- **Per-group communication structures** (`INFO-009`, `INFO-016`, `INFO-012`, `INFO-015`).
  - The delegating parent assigns each group its own communication structure.
  - Options: fan-out only, a shared room, a handoff pipeline, peer links.
  - A child gets exactly the channels its group declares.
- **Groups differ within the same organization.**
  - One group's siblings hand off directly.
  - Another group's siblings may not.
  - The structure is the parent's per-group choice, not a global rule.
- **Cross-group contact.**
  - Happens only through what the parent wired: a designated liaison pair or a shared room.
  - By default, agents of different groups cannot address each other.
- **Escalation is not a group channel** (`INFO-011`).
  - Any agent at any level escalates to its parent, regardless of its group's structure.
- **Supervision applies at every level.**
  - A lead keeps its workers alive the way the root keeps leads alive (`INFO-014`).
  - A lead's death fails its group the way a root's death fails the subtree (`INFO-005`).
- **Organization shape is observable** (`INFO-006`, `INFO-017`).
  - The operator sees the org structure through the same headline-to-summary-to-report tiers as any artifact.

## Owns
- **Multi-level delegation with per-group communication structures.**
  - The parent chooses each group's channels.
  - Children receive exactly those channels.
  - Cross-group contact only via wired links.

## Excludes
- Plain fan-out, the single-level delegation pattern — `INFO-009`.
- **The individual channels themselves.**
  - Sibling handoff — `INFO-012`.
  - Direct messaging — `INFO-015`.
  - The shared room — `INFO-016`.
- **Escalation and supervision mechanics** (`INFO-011`, `INFO-014`, `INFO-005`).
  - This leaf owns only their multi-level composition.
- **Re-decomposition within one agent** (`INFO-010`).
  - A lead's re-decomposition happens inside the group structure it was given.
