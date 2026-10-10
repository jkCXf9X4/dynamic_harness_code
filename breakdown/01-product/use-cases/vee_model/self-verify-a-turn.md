---
id: INFO-003
type: info
title: Self-verify a turn
summary: Each action block analyzes its requirement, implements, verifies against the parents acceptance criteria, and reports
date: 2026-10-05
status: current
---

# Self-verify a turn

- **Action block carries a small V** (`INFO-001`).
  - It analyzes its allocated requirement.
  - It implements.
  - It verifies against the parent's acceptance criteria.
- The block reports its verification result alongside its output.
- **Agent-authored verification logic.**
  - Lives inside the same code block.
  - The runtime injects none of it.

## Owns
- The per-turn V-model discipline enforced on every action.

## Excludes
- Execution and persistence of the block — `INFO-002`.
- Delegation-level verification flow — `INFO-004`.
