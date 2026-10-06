---
id: INFO-036
type: info
title: Isolate each child's REPL and pass context explicitly
summary: Each child works in its own REPL; the parent passes explicit inputs, and nothing of the parent's namespace is shared implicitly
date: 2026-10-06
status: current
---

# Isolate each child's REPL and pass context explicitly

- Every delegated child works in a REPL of its own; siblings' variables cannot collide, and neither child nor parent can accidentally mutate another's workspace (`INFO-030`).
- The parent transfers context explicitly: inputs passed on delegation become the child's defined input context — nothing more is visible.
- The child returns results — a summary plus artifact IDs — to the parent; a child's REPL is never merged into the parent's, and any value the parent wants must be explicitly retained (`INFO-004`).

## Owns
- The child-REPL isolation boundary: private workspace per child, explicit input transfer, explicit result return.

## Excludes
- The per-agent persistent-REPL contract this isolates instances of — `INFO-030`.
- The decomposition contract that defines what parents allocate — `INFO-004`.
- Artifact hand-off between siblings, which routes published artifacts without shared state — `INFO-012`.
