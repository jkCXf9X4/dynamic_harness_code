---
id: INFO-017
type: info
title: Converse with the operator
summary: The operator's request enters at the root agent and the root's result returns to the operator, the only door between human and mesh
date: 2026-10-05
status: current
---

# Converse with the operator

- The operator's request enters at the root agent, and the root's final result returns to the operator; this boundary is the only door between the human and the agent mesh.
- The operator addresses the root, never an inner agent; inner agents reach the operator only by sending their result up through their parent chain to the root (`INFO-006`).
- To inner agents the operator is invisible, with one carve-out: any agent can ask the operator a question through the question channel (`INFO-023`); otherwise no agent outside the root can address the operator or observe the boundary (`INFO-004`).
- The root reports to the operator through the same artifact tiers any consumer pulls (`INFO-006`).
- Hosting the runtime and its container is the operator's concern, one layer out (`INFO-008`).

## Owns
- The operator-to-root boundary channel: the single door by which requests enter and results leave the agent mesh.

## Excludes
- Inter-agent channels, which the root itself also uses — `INFO-015`, `INFO-016`.
- Hosting the runtime in a container — `INFO-008`.
