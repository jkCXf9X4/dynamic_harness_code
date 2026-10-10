---
id: INFO-002
type: info
title: Run a coded action
summary: A worker turn becomes one Python block the runtime persists and executes against the agent's persistent REPL
date: 2026-10-05
status: current
---

# Run a coded action

- **One block per turn**
  - Every agent turn emits one Python block as whole action (`INFO-001`).
- **Persist before execution**
  - Runtime persists block as immutable, content-addressed artifact before execution.
- **Persistent REPL target**
  - Block executes against agent's persistent REPL (`INFO-050`).
- **Result returns compact**
  - Action's result returns to caller as summary plus artifact IDs, not raw logs.
- **One expressive block**
  - One expressive block replaces N tool-call turns.
  - Loops, fan-out, transforms, error handling happen inside action.

## Owns
- Turn-as-code action contract: emit, persist, execute, return.

## Excludes
- How block verifies itself — `INFO-003`.
- Hosting boundary execution runs inside — `INFO-008`.
