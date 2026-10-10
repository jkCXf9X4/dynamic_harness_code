---
id: INFO-019
type: info
title: Set up the whole hierarchy in one action
summary: A single agent spawns every level of a hierarchy in one action and gives each middle agent its already-active subagents and a role message, while communication still routes through the parent chain
date: 2026-10-05
status: current
---

# Set up the whole hierarchy in one action

- **One-shot hierarchy establishment** (`INFO-018`).
  - One agent, typically the root but any agent, establishes the entire hierarchy in a single action.
  - It spawns the agents of all levels, assigns each group's channels, and wires the open links itself.
  - Instead of delegating level by level.
- **Middle-agent spawn payload** (`INFO-018`).
  - Middle agents are spawned with their subagents already active.
  - A message states their role: which subagents they verify results for, and which they solve operational problems for.
  - Not a requirement to decompose.
  - The setter already did the decomposition.
- **Middle agents remain agents with their own turns.**
  - Their work is verification and operational support for their subtree.
  - Not re-decomposition.
- **Communication hierarchy stays fully enforced.**
  - No agent passes over its parent.
  - Results and escalations route up through the parent chain (`INFO-006`, `INFO-011`).
  - Exception: the parties share an open channel the setter wired (`INFO-016`, `INFO-015`).
- **Parenthood follows the structure, not the spawn order** (`INFO-014`, `INFO-005`).
  - Each middle agent is the parent of its own subagents.
  - Supervision, death propagation, and escalation route to the local parent.
  - The setter spawned everyone in one action.
- **Economics differ from level-by-level setup.**
  - The setter's single action replaces the cascade of delegation turns.
  - The hierarchy starts working immediately.
  - Price: the whole decomposition lives in the setter's context.

## Owns
- **One-shot hierarchical setup with role-assigned middle agents.**
  - A single agent establishes all levels in one action.
  - It spawns each middle agent's subagents on its behalf.
  - Results, escalation, and supervision still follow the local parent chain.

## Excludes
- Level-by-level setup where each parent decomposes in its own turn — `INFO-018`.
- The individual channels and patterns — `INFO-009`, `INFO-012`, `INFO-015`, `INFO-016`.
- Extending the structure after the action ends, which is re-decomposition — `INFO-010`.
