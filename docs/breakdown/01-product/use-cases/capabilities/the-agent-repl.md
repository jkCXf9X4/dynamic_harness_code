---
id: INFO-050
type: info
title: The agent REPL
summary: Every agent works in a persistent REPL of its own — private computational workspace, state survives across actions, all agent code executes in it never concurrently, hosts turn engine as workspace code (`__runner` generator, default shipped as fabrication), nothing crosses except explicit context in and explicit results out
date: 2026-10-06
status: current
---

# The agent REPL

- **Persistent computational workspace**
  - Variables, functions, imports, loaded tools survive from one action to next (`INFO-002`).
- **Turn engine is workspace code**
  - `__runner` generator lives in agent's own workspace globals (`INFO-037`).
  - Authored as workspace code: agent can view, edit, replace it like any other variable it owns.
- **Default `__runner` ships as fabrication**
  - `ensure_fabrication` re-seeds fabrication kit if agent breaks or deletes it (`INFO-037`).
  - Fabrication kit: default `__runner`, `decide`, context, channels, checkpoint helpers, caps.
  - Committed turn loop stays default, not second execution path.
- **Expensive intermediates stay live**
  - Embeddings, dataframes, compiled helpers computed once, reused, not recomputed per action.
- **Knowledge accumulates**
  - Notes, helpers, partial results agent builds up stay addressable by later actions.
- **Agent-developed tools live in REPL**
  - Agent-developed tools live in agent's REPL, not harness-provided infrastructure (`INFO-007`).
  - Capability agent adds persists with agent it belongs to.
- **Agent's workspace, not run's**
  - Agent and tools decoupled from harness lifecycle.
  - Not bound to one run.
- State remains available until agent explicitly reset or reaches configured resource boundary.
- **Single execution context**
  - All agent's code executes in agent's own REPL, never concurrently (`INFO-002`, `INFO-033`).
  - Worker actions run there.
  - Registered completion callbacks run there too.
- **Child isolation**
  - Every delegated child works in own REPL.
  - Siblings' variables cannot collide.
  - Neither child nor parent can accidentally mutate another's workspace.
- **Explicit context in**
  - Inputs passed on delegation become child's defined input context.
  - Nothing more visible.
- **Explicit results out**
  - Child returns summary plus artifact IDs to parent (`INFO-004`).
  - Child's REPL never merged into parent's.
  - Any value parent wants must be explicitly retained.

## Owns
- Per-agent REPL contract: private, persistent computational workspace per agent, parent or delegated child.
  - What survives across actions.
  - Lifetime and bounds.
  - Explicit context in, explicit results out at delegation boundary.
  - Single execution context for all that agent's code.

## Excludes
- Turn-as-code action contract executing against it — `INFO-002`.
- Decomposition contract defining what parents allocate — `INFO-004`.
- Artifact store holding durable, cross-agent state — `INFO-006`.
- Agent-developed-tools extension contract workspace carries — `INFO-007`.
- Artifact hand-off between siblings, routes published artifacts without shared state — `INFO-012`.
- Completion-callback contract running inside it — `INFO-033`.
- Turn engine workspace hosts, kernel made real — `INFO-037`.
- Event stream REPL's pull primitives never touch — `INFO-051`.
