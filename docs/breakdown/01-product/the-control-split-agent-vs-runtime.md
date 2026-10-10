---
id: INFO-053
type: info
title: The control split — agent vs runtime
summary: Product-level control boundary: everything reachable in an agent workspace is the agent's to inspect and change. Every mesh-survival guarantee is runtime behavior no agent code can edit or skip.
date: 2026-10-08
status: current
---

# The control split — agent vs runtime

The runtime commits to one fixed control boundary.
Everything reachable inside an agent's workspace is the agent's to inspect and change.
Every guarantee the mesh depends on is runtime behavior, evaluated outside agent code.
It is not data the agent holds, so there is nothing to edit and nothing to defeat (`INFO-052`).
The split is not about visibility: caps and tripwires are visible to the agent too.
It is about who enforces.

## Under agent control

- **The main loop.**
  - How the agent works, including orchestration cadence, is workspace code.
  - Agent views, edits, replaces it.
  - The default loop ships as a fabrication the agent starts from (`INFO-050`).
- **The decision policy.** How the next action is chosen, including prompt assembly, is a workspace function the agent may swap.
- **Context and history.**
  - Agent reads and manages its full accumulated state as ordinary data.
  - State includes digests, inbox and outbox, workspace variables.
  - No pre-filtered view of itself.
- **Working budgets and tripwires.** Agent sets its own working limits and rot policy as ordinary data, within the ceilings.
- **Guardrail content.**
  - Self-authored rules are workspace data.
  - Parent-imposed normative constraints arrive as visible context the agent reasons over.
- **Parent-side reaction policy.** How an agent, as parent, reacts to a child's rot or failure runs in the parent's own execution, never in the child.
- **Event consumption.** Which of its settled events the agent reads, and when.
- **Waiting.**
  - How the agent waits: await, poll, sleep.
  - Waiting on others consumes no agent budget.
  - Parked time (await on a child, sleep) is credited against the wall-clock ceiling.
  - How the credit is measured: `INFO-060`.
- **Tools.** Agent-developed tools are workspace variables (`INFO-007`).

## Under runtime control

The first four items are the hard gates, the mesh-survival core (`INFO-037`).
The rest are runtime-owned correctness beyond survival.

- **Settlement.**
  - A result settles at most once (`INFO-046`).
  - No loop rewrite changes that.
- **Containment.**
  - A failed, hung, or runaway agent is contained, rolled back, and settles failed.
  - The mesh stays up.
  - The workspace is the blast radius (`INFO-005`).
- **Ceiling caps.**
  - Wall-clock, step count, workspace size, child count, message rate bind regardless of any budget edit the agent makes.
  - The wall-clock ceiling binds all non-parked wall time.
  - The credit is runtime-owned and never exceeds elapsed time.
  - A parked-forever agent is contained by cancellation, not the wall clock.
  - Clock base and measurement: `INFO-060`.
- **Cancellation.** A cancelled agent gets a grace window, then is stopped and settled (`INFO-040`).
- **Event discipline.**
  - FIFO, at-most-once delivery, persist-before-execute (`INFO-048`).
  - Consumption is the agent's.
  - The guarantees are the runtime's (`INFO-051`).
- **Enforcement timing.**
  - Tripwires and caps are evaluated between agent actions by the runtime.
  - A degrading agent cannot skip its own leash.
- **Completion dispatch.** Child completions reach the parent through the runtime's dispatcher (`INFO-047`), never by child-side code.
- **Fabrication integrity.** A broken or deleted default (loop, decision policy, context) is re-seeded by the runtime (`AD-011`).
- **Directed-message delivery.** Routing, rate cap, and persistence of a directed message are runtime behavior; the message reaches the recipient's awareness (`INFO-054`).

## Owns

- **Product-level control split.**
  - Agent-controlled surface.
  - Runtime-guaranteed surface.
  - Separating principle: agent freedom ends exactly where mesh survival begins.

## Excludes

- **Why the split exists.** `INFO-052`.
- **The candidate and its adoption state.** `IMP-001`.
- **How the split is implemented.** The architecture layer.
- **Guardrail content semantics and rot detection.** `INFO-021`.
- **The delegation contract.** `INFO-004`.
- **REPL and event-stream use cases in detail.** `INFO-050`, `INFO-051`.
- **The orthogonal boundary of what the framework core carries.** `INFO-054`.
