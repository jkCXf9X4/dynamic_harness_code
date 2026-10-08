---
id: INFO-050
type: info
title: The agent REPL
summary: Every agent works in a persistent REPL of its own — a private computational workspace whose state survives across actions, that all of the agent's code executes in and never concurrently, that hosts the turn engine as workspace code (the `__runner` generator, default shipped as a fabrication), and that nothing crosses except explicit context in and explicit results out
date: 2026-10-06
status: current
---

# The agent REPL

- The REPL is the agent's persistent computational workspace: variables, functions, imports, and loaded tools survive from one action to the next (`INFO-002`).
- The turn engine — the agent's main loop — is workspace code: the `__runner` generator lives in the agent's own workspace globals, authored as workspace code so the agent can view, edit, and replace it like any other variable it owns (`INFO-037`).
- The default `__runner` ships as a fabrication: `ensure_fabrication` re-seeds the fabrication kit (default `__runner`, `decide`, context, channels, checkpoint helpers, caps) if the agent breaks or deletes it, so the committed turn loop is the default, not a second execution path (`INFO-037`).
- Expensive intermediates stay live — embeddings, dataframes, and compiled helpers are computed once and reused instead of recomputed per action.
- Agent-generated knowledge accumulates in the workspace: notes, helpers, and partial results the agent builds up stay addressable by later actions.
- Agent-developed tools live in the agent's REPL, not in harness-provided infrastructure — a capability the agent adds persists with the agent it belongs to (`INFO-007`).
- The REPL is the agent's workspace, not the run's: agent and tools are decoupled from the harness lifecycle instead of bound to one run.
- State remains available until the agent is explicitly reset or reaches a configured resource boundary.
- All of an agent's code executes in that agent's own REPL, never concurrently: worker actions run there, and so do the completion callbacks the agent registers (`INFO-002`, `INFO-033`).
- Every delegated child works in a REPL of its own; siblings' variables cannot collide, and neither child nor parent can accidentally mutate another's workspace.
- The parent transfers context explicitly: inputs passed on delegation become the child's defined input context — nothing more is visible.
- The child returns results — a summary plus artifact IDs — to the parent; a child's REPL is never merged into the parent's, and any value the parent wants must be explicitly retained (`INFO-004`).

## Owns
- The per-agent REPL contract: a private, persistent computational workspace per agent — parent or delegated child — what survives across actions, its lifetime and bounds, explicit context in and explicit results out at the delegation boundary, and its role as the single execution context for all of that agent's code.

## Excludes
- The turn-as-code action contract that executes against it — `INFO-002`.
- The decomposition contract that defines what parents allocate — `INFO-004`.
- The artifact store that holds durable, cross-agent state — `INFO-006`.
- The agent-developed-tools extension contract the workspace carries — `INFO-007`.
- Artifact hand-off between siblings, which routes published artifacts without shared state — `INFO-012`.
- The completion-callback contract that runs inside it — `INFO-033`.
- The turn engine the workspace hosts — the kernel made real — `INFO-037`.
- The event stream the REPL's pull primitives never touch — `INFO-051`.
