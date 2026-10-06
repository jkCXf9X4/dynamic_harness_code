---
id: INFO-002
type: info
title: Run a coded action
summary: A worker turn becomes one Python block the runtime persists and executes against the agent's persistent REPL
date: 2026-10-05
status: current
---

# Run a coded action

- Every agent turn emits one Python block as its whole action (`INFO-001`).
- The runtime persists the block as an immutable, content-addressed artifact before execution.
- The block executes against the agent's persistent REPL (`INFO-030`).
- The action's result returns to the caller as a summary plus artifact IDs, not raw logs.
- One expressive block replaces N tool-call turns: loops, fan-out, transforms, and error handling happen inside the action.

## Owns
- The turn-as-code action contract: emit, persist, execute, and return.

## Excludes
- How the block verifies itself — `INFO-003`.
- The hosting boundary the subprocess runs inside — `INFO-008`.
