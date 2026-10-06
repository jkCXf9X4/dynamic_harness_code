---
id: INFO-030
type: info
title: Give each agent a persistent REPL
summary: Each agent works in a persistent REPL of its own — state persists across actions, agent-developed tools live in it, and it is the agent's workspace rather than the run's
date: 2026-10-06
status: current
---

# Give each agent a persistent REPL

- The agent's REPL is its persistent computational workspace: variables, functions, imports, and loaded tools survive from one action to the next (`INFO-002`).
- Expensive intermediates stay live — embeddings, dataframes, and compiled helpers are computed once and reused instead of recomputed per action.
- Agent-generated knowledge accumulates in the workspace: notes, helpers, and partial results the agent builds up stay addressable by later actions.
- Agent-developed tools live in the agent's REPL, not in harness-provided infrastructure — a capability the agent adds persists with the agent it belongs to (`INFO-007`).
- The REPL is the agent's workspace, not the run's: agent and tools are decoupled from the harness lifecycle instead of bound to one run.
- State remains available until the agent is explicitly reset or reaches a configured resource boundary.

## Owns
- The per-agent persistent-REPL contract: workspace lifetime, what survives across actions, and what bounds it.

## Excludes
- The turn-as-code action contract that executes against it — `INFO-002`.
- The artifact store that holds durable, cross-agent state — `INFO-006`.
- The agent-developed-tools extension contract the workspace carries — `INFO-007`.
