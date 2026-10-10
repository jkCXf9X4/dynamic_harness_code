---
id: INFO-004
type: info
title: Decompose a task recursively
summary: A parent writes delegation code that spawns encapsulated child workers and receives summaries plus artifact IDs
date: 2026-10-05
status: current
---

# Decompose a task recursively

- Parent decomposes work by writing delegation code, not by calling fixed tools (`INFO-001`).
- **Encapsulated child context, nothing more** (`INFO-050`).
  - The child's allocated requirement.
  - The parent's acceptance criteria.
  - Explicitly passed inputs.
- **Child output: summary plus artifact IDs** (`INFO-006`).
  - The parent pulls detail on demand.
- **Delegation overhead.**
  - Stays near 3K tokens per child.
  - Decomposed 3-turn workers beat a 20-turn monolith.
  - The monolith rots past 15K.

## Owns
- Recursive task decomposition via delegation code.
- The context-encapsulation contract between parent and child.

## Excludes
- Crash containment and failure surfacing — `INFO-005`.
- The per-turn action loop — `INFO-002`.
- The child-REPL isolation the context transfer rides on — `INFO-050`.
