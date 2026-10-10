---
id: INFO-017
type: info
title: Converse with the operator
summary: The operator's request enters at the root agent and the root's result returns to the operator, the only door between human and mesh
date: 2026-10-05
status: current
---

# Converse with the operator

- **Single door**
  - Operator's request enters at root agent.
  - Root's final result returns to operator.
  - Boundary only door between human and agent mesh.
- **Operator addresses root only**
  - Never an inner agent.
  - Inner agents reach operator only by sending result up through parent chain to root (`INFO-006`).
- **Invisible to inner agents, one carve-out**
  - Any agent can ask operator question through question channel (`INFO-023`).
  - Otherwise no agent outside root can address operator or observe boundary (`INFO-004`).
- **Reporting route**
  - Root reports to operator through same artifact tiers any consumer pulls (`INFO-006`).
- **Hosting**
  - Runtime and its container: operator's concern, one layer out (`INFO-008`).

## Owns
- Operator-to-root boundary channel: single door by which requests enter and results leave agent mesh.

## Excludes
- Inter-agent channels, which root itself also uses — `INFO-015`, `INFO-016`.
- Hosting the runtime in a container — `INFO-008`.
