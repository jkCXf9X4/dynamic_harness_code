---
id: INFO-020
type: info
title: Survive an LLM call timing out or terminating
summary: A timed-out or terminated LLM call fails the turn safely and surfaces as a failed result instead of hanging or crashing the agent
date: 2026-10-05
status: current
---

# Survive an LLM call timing out or terminating

- Every agent turn depends on an LLM call, and an LLM call can time out or terminate without returning a completion.
- A timed-out or terminated LLM call is contained to the turn: the agent survives and keeps running (`INFO-001`).
- The failure surfaces as a failed result for the turn, indistinguishable in shape from a success (`INFO-005`).
- The parent treats it like any other failed result and may re-decompose or escalate (`INFO-011`).

## Owns
- LLM-call failure containment and surfacing: a timed-out or terminated LLM call fails the turn safely instead of hanging or crashing the agent.

## Excludes
- Crash containment for the child process itself — `INFO-005`.
- Retry, timeout-budget, or re-decomposition policy after a failure — `INFO-004`.
- The action loop whose LLM call failed — `INFO-002`.
