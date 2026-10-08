---
id: INFO-052
type: info
title: Agent-owned execution — goal and vision
summary: The direction behind IMP-001: agents own their execution, the platform becomes a minimal guardian, and freedom is bounded only by the survival of the mesh
date: 2026-10-08
status: current
---

# Agent-owned execution — goal and vision

The direction the runtime takes is **agent self-ownership**: the agent owns
its execution; the platform is a minimal guardian. This leaf holds that
direction at intent level. `INFO-001` states the substrate mission it rides
on; `IMP-001` is the candidate that carries it; mechanism lives in the
decision records and the architecture layer, not here.

## Vision — an agent that owns itself

- The agent is the author of its own way of working: it sees its full history
  and state, shapes its own decision-making, writes its own rules, and can
  change any of these mid-run.
- The agent is a sovereign citizen of its own workspace, not a component the
  platform drives.
- The platform's role inverts from orchestrator to minimal guardian: the
  runtime does not embody the intelligence of how work gets done — it
  guarantees only that the whole system survives, no matter what any agent
  does to itself.
- Orchestration intelligence moves into the workspace; the platform keeps
  only the invariants. `INFO-037` names this "the kernel made real".

## Goal — invert the ownership of execution

- **From runtime-owned loop to agent-owned loop.** How an agent works is
  something the agent itself can inspect and rewrite, not fixed platform
  code.
- **From lossy visibility to full transparency.** The agent reads and manages
  its own context, budgets, and guardrails as ordinary data — no
  pre-filtered view of itself, no injection channels, no hidden state.
- **From enforced uniformity to safe experimentation.** An agent can try a
  different way of working, fail at it, and recover; the blast radius of
  that failure is exactly one agent.
- **From expensive supervision to cheap cooperation.** Waiting on others
  does not consume an agent's own capacity to act.

## Invariant — freedom bounded by the survival of the mesh

Everything an agent can reach, it may change — including its own rules and
limits. The few guarantees that must never be violated (containment,
finality, ceilings, cancellation) are not things the agent has, so it cannot
defeat them. A degrading agent can break itself; it can never break the
system.

## Scope of the direction

This is a change in **who holds power**, not a performance change and not a
capability add: intelligence and policy move down into the agent; the
platform retains only what must be trusted. The bet behind it — agents
trusted with themselves, behind a thin layer of non-negotiable guarantees,
become more capable and more honest than blind, tightly-driven workers.

## Owns
- The intent-level goal and vision of agent-owned execution: self-ownership,
  the inverted platform role (orchestrator → minimal guardian), and the
  freedom-bounded-by-mesh-survival invariant.

## Excludes
- The substrate mission, principles, and action loop — `INFO-001`.
- The improvement candidate, its pain and evidence, and its adoption state —
  `IMP-001`.
- Mechanism: executor shape, gate layer, op vocabulary, defaults, guardrail
  placement — the `IMP-001` decision records and the architecture layer.
