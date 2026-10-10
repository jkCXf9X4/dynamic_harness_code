---
id: INFO-021
type: info
title: Detect context rot in an agent's output
summary: The runtime detects degradation signatures in an agent's output; the agent's rot policy (observe-only default, or escalate) decides whether a trip settles the agent and surfaces to the parent
date: 2026-10-05
status: current
---

# Detect context rot in an agent's output

- **Degradation signatures**
  - Runtime monitors each agent's output stream for degradation signatures.
  - Signatures: repeating loops of near-identical actions, gibberish, degenerate repetition.
- **Runtime-owned detection**
  - Detection is runtime-owned instrumentation: heuristics invisible to and never authored by agent (`INFO-001`).
- **Authorable policy half**
  - Rot *policy* is authorable half: `context.rot_policy`, ordinary workspace data agent may set and edit.
  - Threshold min-clamped to detector default, so can only tighten.
  - Reaction: `observe` by default, or `escalate`.
- **Check placement**
  - Check runs in pump between agent actions, so degrading agent cannot skip own leash.
- **Observe-only default**
  - Detected degradation logged, block returned unchanged.
  - Nothing surfaces to parent.
- **Escalate reaction**
  - Trip settles agent failed: containment (`INFO-005`).
  - Completion publishes to parent's stream: completion-style event, shaped like escalation (`INFO-011`).
- **Parent-side reaction**
  - Parent's completion callback (`on_done`) runs in parent's worker loop.
  - Child never executes own termination.
- **Propagation**
  - Propagates up parent chain to operator like any other child report (`INFO-014`).

## Owns
- Detection and surfacing of context rot: degradation signatures recognized, where signal lands.

## Excludes
- Response policy on degraded signal: terminate, restart, or re-decompose — `INFO-004`.
- Crash containment for failed child — `INFO-005`.
- LLM-call failure, transport-level fault distinct from this — `INFO-020`.
