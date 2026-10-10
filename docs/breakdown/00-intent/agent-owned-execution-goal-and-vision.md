---
id: INFO-052
type: info
title: Agent-owned execution — goal and vision
summary: Direction behind IMP-001: agents own their execution, platform becomes a minimal guardian, freedom bounded only by mesh survival
date: 2026-10-10
status: current
---

# Agent-owned execution — goal and vision

Runtime direction is **agent self-ownership**. Agent owns its execution. Platform is a minimal guardian.
This leaf holds that direction at intent level. `INFO-001` states the substrate mission it rides on. `IMP-001` carried it and is implemented. The landed control split is `INFO-053`; the realized kernel is `INFO-037`. Mechanism lives in the decision records and the architecture layer, not here.

## Vision — an agent that owns itself

- **Self-authoring.** Agent is the author of its own way of working.
  - It sees its full history and state.
  - It shapes its own decision-making.
  - It writes its own rules.
  - It can change any of these mid-run.
- **Sovereign.** Agent is a sovereign citizen of its own workspace, not a component the platform drives.
- **Inverted role.**
  - Platform is a minimal guardian, not an orchestrator.
  - Runtime does not embody the intelligence of how work gets done.
  - It guarantees only that the whole system survives.
  - That holds no matter what any agent does to itself.
  - Operator side of the split is unchanged: medium around the core stays operator tooling (`INFO-054`).
- **Kernel made real.**
  - Orchestration intelligence lives in the workspace, not in platform code.
  - Platform keeps only the invariants.
  - `INFO-037` names this "the kernel made real".

## Goal — invert the ownership of execution

- **Runtime-owned loop to agent-owned loop.**
  - How an agent works is something the agent itself can inspect and rewrite, not fixed platform code.
- **Lossy visibility to full transparency.**
  - Agent reads and manages its own context, budgets, guardrails as ordinary data.
  - No pre-filtered view of itself.
  - No injection channels.
  - No hidden state.
- **Enforced uniformity to safe experimentation.**
  - Agent can try a different way of working, fail at it, recover.
  - Failure blast radius is exactly one agent.
- **Expensive supervision to cheap cooperation.**
  - Waiting on others does not consume an agent's own capacity to act.

## Invariant — freedom bounded by the survival of the mesh

Everything an agent can reach, it may change — including its own rules and limits.
The few guarantees that must never be violated: settlement, containment, ceiling caps, cancellation (`INFO-053`).
Those guarantees are not things the agent has, so it cannot defeat them.
A degrading agent can break itself. It can never break the system.

## Scope of the direction

This is a change in **who holds power**. Not a performance change. Not a capability add.
Intelligence and policy move down into the agent. Platform retains only what must be trusted.
The bet: agents trusted with themselves, behind a thin layer of non-negotiable guarantees. They become more capable and more honest than blind, tightly-driven workers.

## Owns

- **Intent-level goal and vision.**
  - Self-ownership.
  - Inverted platform role: orchestrator to minimal guardian.
  - Freedom-bounded-by-mesh-survival invariant.

## Excludes

- **Substrate mission.** The substrate mission, principles, and action loop — `INFO-001`.
- **The landed control split.** Agent-controlled and runtime-guaranteed surfaces — `INFO-053`.
- **Improvement candidate.** Its pain, evidence, adoption state — `IMP-001`.
- **Mechanism.**
  - Executor shape, gate layer, op vocabulary, defaults, guardrail placement.
  - Lives in the `IMP-001` decision records and the architecture layer.
