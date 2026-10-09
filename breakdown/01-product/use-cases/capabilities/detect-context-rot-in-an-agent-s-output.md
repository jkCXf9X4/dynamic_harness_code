---
id: INFO-021
type: info
title: Detect context rot in an agent's output
summary: The runtime detects degradation signatures in an agent's output; the agent's rot policy (observe-only default, or escalate) decides whether a trip settles the agent and surfaces to the parent
date: 2026-10-05
status: current
---

# Detect context rot in an agent's output

- The runtime monitors each agent's output stream for degradation signatures: repeating loops of near-identical actions, gibberish, and degenerate repetition.
- Detection is runtime-owned instrumentation: the heuristics are invisible to and never authored by the agent (`INFO-001`).
- The agent's rot *policy* is the authorable half: `context.rot_policy` is ordinary workspace data the agent may set and edit — a threshold (min-clamped to the detector default, so it can only tighten) and a reaction (`observe` by default, or `escalate`).
- The check runs in the pump between agent actions, so a degrading agent cannot skip its own leash.
- Observe-only is the default: a detected degradation is logged and the block returned unchanged — nothing surfaces to the parent.
- Under `escalate`, a trip settles the agent failed (containment, `INFO-005`) and the Completion publishes to the parent's stream — a completion-style event, shaped like an escalation (`INFO-011`).
- The reaction is parent-side: the parent's completion callback (`on_done`) runs in the parent's worker loop; the child never executes its own termination.
- From the parent it propagates up the parent chain to the operator like any other child report (`INFO-014`).

## Owns
- Detection and surfacing of context rot: the degradation signatures recognized and where the signal lands.

## Excludes
- Response policy on a degraded signal — terminate, restart, or re-decompose — `INFO-004`.
- Crash containment for a failed child — `INFO-005`.
- LLM-call failure, the transport-level fault this is distinct from — `INFO-020`.
