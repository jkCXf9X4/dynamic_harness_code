---
id: INFO-004
type: info
title: Decompose a task recursively
summary: A parent writes delegation code that spawns encapsulated child workers and receives summaries plus artifact IDs
date: 2026-10-05
status: current
---

# Decompose a task recursively

- A parent decomposes work by writing delegation code, not by calling fixed tools (`INFO-001`).
- Each child worker starts in its own REPL with an encapsulated context: its allocated requirement, the parent's acceptance criteria, and explicitly passed inputs — nothing more (`INFO-030`).
- A child returns a summary plus artifact IDs; the parent pulls detail on demand — `INFO-006`.
- Delegation overhead stays near 3K tokens per child, so decomposed 3-turn workers beat a 20-turn monolith that rots past 15K.

## Owns
- Recursive task decomposition via delegation code.
- The context-encapsulation contract between parent and child.

## Excludes
- Crash containment and failure surfacing — `INFO-005`.
- The per-turn action loop — `INFO-002`.
- The child-REPL isolation the context transfer rides on — `INFO-030`.
