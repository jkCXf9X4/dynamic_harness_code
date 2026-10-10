---
id: INFO-053
type: info
title: The control split — agent vs runtime
summary: The product-level control boundary: everything reachable in an agent's workspace is the agent's to inspect and change; every mesh-survival guarantee is runtime behavior no agent code can edit or skip
date: 2026-10-08
status: current
---

# The control split — agent vs runtime

The runtime commits to one fixed control boundary. Everything reachable
inside an agent's workspace is the agent's to inspect and change; every
guarantee the mesh depends on is runtime behavior, evaluated outside agent
code — not data the agent holds, so there is nothing to edit and nothing to
defeat. The split is not about visibility: caps and tripwires are visible to
the agent too. It is about who enforces.

## Under agent control

- **The main loop.** How the agent works — orchestration and its cadence —
  is workspace code the agent views, edits, and replaces; the default loop
  ships as a fabrication the agent starts from.
- **The decision policy.** How the next action is chosen, including prompt
  assembly, is a workspace function the agent may swap.
- **Context and history.** The agent reads and manages its full accumulated
  state — digests, inbox and outbox, workspace variables — as ordinary
  data; there is no pre-filtered view of itself.
- **Working budgets and tripwires.** The agent sets its own working limits
  and rot policy as ordinary data, within the ceilings.
- **Guardrail content.** Self-authored rules are workspace data;
  parent-imposed normative constraints arrive as visible context the agent
  reasons over.
- **Parent-side reaction policy.** How an agent, as parent, reacts to a
  child's rot or failure runs in the parent's own execution, never in the
  child.
- **Event consumption.** Which of its settled events the agent reads, and
  when.
- **Waiting.** How the agent waits — await, poll, sleep; waiting on others
  consumes no agent budget. Parked time (await on a child, sleep) is credited
  against the wall-clock ceiling: the pump accumulates the seconds each agent
  spends parked and passes the cumulative credit to the caps watchdog.
- **Tools.** Agent-developed tools are workspace variables (`INFO-007`).

## Under runtime control

- **Settlement.** A result settles at most once (`INFO-046`); no loop
  rewrite changes that.
- **Containment.** A failed, hung, or runaway agent is contained, rolled
  back, and settles failed; the mesh stays up. The workspace is the blast
  radius (`INFO-005`).
- **Ceiling caps.** Wall-clock, step count, workspace size, child count, and
  message rate bind regardless of any budget edit the agent makes. The
  wall-clock ceiling binds all non-parked wall time; the credit is
  runtime-owned (measured by the pump around suspend/resume, clamped at
  zero, never exceeding elapsed time). A parked-forever agent is contained by
  cancellation, not the wall clock.
- **Cancellation.** A cancelled agent gets a grace window, then is stopped
  and settled (`INFO-040`).
- **Event discipline.** FIFO, at-most-once delivery, persist-before-execute
  (`INFO-049`); consumption is the agent's, the guarantees are the
  runtime's (`INFO-051`).
- **Enforcement timing.** Tripwires and caps are evaluated between agent
  actions by the runtime; a degrading agent cannot skip its own leash.
- **Completion dispatch.** Child completions reach the parent through the
  runtime's dispatcher (`INFO-047`), never by child-side code.
- **Fabrication integrity.** A broken or deleted default (loop, decision
  policy, context) is re-seeded by the runtime.

## Owns
- The product-level control split: the agent-controlled surface, the
  runtime-guaranteed surface, and the principle that separates them — agent
  freedom ends exactly where mesh survival begins.

## Excludes
- Why the split exists — `INFO-052`; the candidate and its adoption state —
  `IMP-001`.
- How the split is implemented — the architecture layer.
- Guardrail content semantics and rot detection — `INFO-021`; the delegation
  contract — `INFO-004`.
- The REPL and event-stream use cases in detail — `INFO-050`, `INFO-051`.
- The orthogonal boundary of what the framework core carries — `INFO-054`.
