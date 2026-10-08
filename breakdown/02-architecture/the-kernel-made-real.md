---
id: INFO-037
type: info
title: The kernel made real — the turn engine as a workspace-owned resumable generator
summary: The turn engine is made real as a workspace-owned, agent-authored resumable generator that the runtime pumps one yield-window at a time under a small hard-gate layer — the kernel in user space
date: 2026-10-07
status: current
---

# The kernel made real — the turn engine as a workspace-owned resumable generator

- The turn engine (the agent's main loop) is a **resumable generator** living in the agent's own workspace globals (`__runner`), authored as workspace code so the agent can view, edit, and replace it like any other variable it owns.
- The runtime shrinks to a **pump**: it advances the generator one yield-window (one *step*) at a time, classifies what it yielded, enforces the hard gates, and repeats. The agent owns the orchestration intelligence; the pump owns preemption and integrity.
- **A yield is a checkpoint.** Between yields the workspace is consistent, so the pump snapshots cheaply; cancellation lands between steps; per-step budgeting is exact instead of per-turn.
- **The op vocabulary is split by cost.** Bounded, synchronous operations are direct workspace calls (`run_block`, inbox drain, guardrail/budget edits). Indefinite or off-thread operations are `yield` requests serviced by the pump: `yield Await(handle)`, `yield Poll(handle)`, `yield Sleep(t)`. A parent can `yield Await(child)` without consuming step budget.
- **The four hard gates are pump behavior, not workspace variables:** (1) settlement at-most-once, (2) crash containment / blast radius, (3) outer ceiling caps (wall-clock, step count, workspace size, child count, message rate), (4) cancellation grace. A degrading agent can break itself; it can never break the mesh.
- **The default `__runner` replicates the committed turn loop exactly** (decide → run_block → observe → settle); backward compatibility is "the default fabrication," not a second execution path. `ensure_fabrication` re-seeds any fabrication the agent broke or deleted.
- This is the "kernel made real" (`INFO-052`): orchestration intelligence moves into the workspace; the platform keeps only the invariants.

## Owns
- The kernel-made-real contract: the turn engine as a workspace-owned, agent-authored resumable generator, the pump, the four hard gates, and the fabrication kit (defaults, decide, context, channels, checkpoint helpers, caps).

## Excludes
- The agent REPL the kernel lives in — `INFO-050`.
- The event-stream resolution the kernel's observe step consumes — `INFO-048`.
- The completion dispatch the kernel's yield servicing rides on — `INFO-047`.
- The boundary event log the kernel's per-step events flow through — `INFO-049`.
- The agent concurrency placement the pump runs on — `INFO-038`.
- The improvement candidate that carries this contract and its adoption state — `IMP-001`.
