---
id: INFO-021
type: info
title: Detect context rot in an agent's output
summary: The runtime detects degradation signatures such as repeating loops and gibberish in an agent's output stream and surfaces them to the parent
date: 2026-10-05
status: current
---

# Detect context rot in an agent's output

- The runtime monitors each agent's output stream for degradation signatures: repeating loops of near-identical actions, gibberish, and degenerate repetition.
- Detection is runtime-owned instrumentation, invisible to and never authored by the agent (`INFO-001`).
- A detected degradation surfaces to the parent as a signal alongside the result, shaped like an escalation (`INFO-011`).
- From the parent it propagates up the parent chain to the operator like any other child report (`INFO-014`).

## Owns
- Detection and surfacing of context rot: the degradation signatures recognized and where the signal lands.

## Excludes
- Response policy on a degraded signal — terminate, restart, or re-decompose — `INFO-004`.
- Crash containment for a failed child — `INFO-005`.
- LLM-call failure, the transport-level fault this is distinct from — `INFO-020`.
