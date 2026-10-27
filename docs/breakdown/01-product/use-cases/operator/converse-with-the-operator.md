---
id: INFO-017
type: info
title: Converse with the operator
summary: The operator's request enters at the root agent and the root's result returns to the operator, the only door between human and mesh
date: 2026-10-05
status: current
---

# Converse with the operator

- **Default door is root**
  - Operator's request enters at the root agent.
  - Root's final result returns to the operator.
  - Boundary is the only door between human and agent mesh.
  - Steering may address a specific agent by identity (`INFO-022`).
- **Inner agents reach the operator through the mesh**
  - Results travel up the parent chain to root (`INFO-006`).
  - Any agent can ask the operator a question (`INFO-023`).
- **Reporting route**
  - Root reports to operator through same artifact tiers any consumer pulls (`INFO-006`).
- **Hosting**
  - Runtime and its container: operator's concern, one layer out (`INFO-008`).

## Owns
- Operator-to-root boundary channel: single door by which requests enter and results leave agent mesh.

## Excludes
- Inter-agent channels, which root itself also uses — `INFO-015`, `INFO-016`.
- Hosting the runtime in a container — `INFO-008`.
- The operator door and channel composition the runtime exposes — `INFO-058`.
