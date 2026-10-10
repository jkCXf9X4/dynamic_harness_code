---
id: INFO-020
type: info
title: Survive an LLM call timing out or terminating
summary: A timed-out or terminated LLM call fails the turn safely and surfaces as a failed result instead of hanging or crashing the agent
date: 2026-10-05
status: current
---

# Survive an LLM call timing out or terminating

- **Dependency**
  - Every agent turn depends on LLM call.
  - LLM call can time out or terminate without returning completion.
- **Contained to turn**
  - Timed-out or terminated LLM call contained to turn (`INFO-001`).
  - Agent survives, keeps running.
- **Failed result surfaced**
  - Failure surfaces as failed result for turn (`INFO-005`).
  - Shape indistinguishable from success.
- **Parent handling**
  - Parent treats like any other failed result (`INFO-011`).
  - May re-decompose or escalate.

## Owns
- LLM-call failure containment and surfacing: timed-out or terminated LLM call fails turn safely instead of hanging or crashing agent.

## Excludes
- Crash containment for child process itself — `INFO-005`.
- Retry, timeout-budget, or re-decomposition policy after failure — `INFO-004`.
- Action loop whose LLM call failed — `INFO-002`.
