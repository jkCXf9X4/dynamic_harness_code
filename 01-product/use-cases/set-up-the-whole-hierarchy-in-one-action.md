---
id: INFO-019
type: info
title: Set up the whole hierarchy in one action
summary: A single agent spawns every level of a hierarchy in one action and gives each middle agent its already-active subagents and a role message, while communication still routes through the parent chain
date: 2026-10-05
status: current
---

# Set up the whole hierarchy in one action

- One agent — typically the root, but any agent — establishes the entire hierarchy in a single action: it spawns the agents of all levels, assigns each group's channels, and wires the open links itself, instead of delegating level by level (`INFO-018`).
- Middle agents are spawned with their subagents already active and a message stating their role: which subagents they verify results for and solve operational problems for — not a requirement to decompose, since the setter already did the decomposition (`INFO-018`).
- Middle agents remain agents with their own turns; their work is verification and operational support for their subtree, not re-decomposition.
- The communication hierarchy stays fully enforced: no agent passes over its parent — results and escalations route up through the parent chain (`INFO-006`, `INFO-011`) — unless the parties share an open channel the setter wired (`INFO-016`, `INFO-015`).
- Parenthood follows the structure, not the spawn order: each middle agent is the parent of its own subagents, so supervision, death propagation, and escalation route to the local parent even though the setter spawned everyone in one action (`INFO-014`, `INFO-005`).
- The economics differ from level-by-level setup: the setter's single action replaces the cascade of delegation turns, so the hierarchy starts working immediately, at the price of the whole decomposition living in the setter's context.

## Owns
- One-shot hierarchical setup with role-assigned middle agents: a single agent establishes all levels in one action, spawning each middle agent's subagents on its behalf, while results, escalation, and supervision still follow the local parent chain.

## Excludes
- Level-by-level setup where each parent decomposes in its own turn — `INFO-018`.
- The individual channels and patterns — `INFO-009`, `INFO-012`, `INFO-015`, `INFO-016`.
- Extending the structure after the action ends, which is re-decomposition — `INFO-010`.
