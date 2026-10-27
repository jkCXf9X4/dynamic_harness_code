---
id: INFO-052
type: info
title: Agent-owned execution — direction
summary: The power inversion behind dhc: agents own their execution, the platform becomes a minimal guardian, and freedom stops only at mesh survival
date: 2026-10-27
status: current
---

# Agent-owned execution — direction

The direction is agent self-ownership.
The agent owns its execution.
The platform is a minimal guardian.
The substrate it rides on is `INFO-001`.
The landed split is `INFO-053`.
The realized kernel is `INFO-037`.
This leaf holds the why and the power shift only.

## The inversion

- **Who decides moves down.**
  - Orchestration intelligence lives in the workspace, not in platform code (`INFO-037`).
- **Who guarantees stays up.**
  - The runtime keeps only the invariants that must be trusted (`INFO-053`).
- **The operator side does not move.**
  - Medium around the core stays operator tooling (`INFO-054`).

## Goal deltas

- **Runtime-owned loop to agent-owned loop.**
  - How an agent works is something it can inspect and rewrite.
- **Lossy view to full view.**
  - The agent reads its own context, budgets, and guardrails as ordinary data.
  - No pre-filtered view, no injection channel, no hidden state.
- **Uniformity to safe experimentation.**
  - The agent may try a different way of working, fail, and recover.
  - Failure blast radius is exactly one agent (`INFO-005`).
- **Supervision to cooperation.**
  - Waiting on others consumes no capacity to act (`INFO-053`).

## Invariant

Everything an agent can reach, it may change, including its own rules and limits.
Four hard gates sit outside its reach (`INFO-001`, `INFO-053`).
They are not things the agent holds, so it cannot defeat them.
A degrading agent can break itself.
It can never break the system.

## What this is

- **A change in who holds power.**
  - Not a performance change.
  - Not a capability add.
- **A bet on trust.**
  - Agents trusted with themselves become more capable and more honest than tightly-driven workers.
  - Thin guarantees are what make that trust safe to extend.

## Owns
- The intent-level direction: self-ownership, the inverted platform role, and the survival invariant.

## Excludes
- The substrate mission, bet, commitments, and precedence — `INFO-001`.
- The control split detail — `INFO-053`.
- Which workflows the agent authors — `INFO-074`.
- Candidate history and adoption state — `IMP-001`.
- Mechanism: executor shape, gate layer, defaults, guardrail placement — the Architecture layer.
