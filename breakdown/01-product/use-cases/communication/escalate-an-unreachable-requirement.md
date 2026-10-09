---
id: INFO-011
type: info
title: Escalate an unreachable requirement
summary: A child whose acceptance criteria prove unreachable reports a failed result with a reason and the parent re-allocates
date: 2026-10-05
status: current
---

# Escalate an unreachable requirement

- A child whose acceptance criteria prove unreachable reports a failed result carrying the reason, instead of a partial success (`INFO-005`).
- The escalation travels upstream only: the parent re-allocates by re-decomposing, relaxing the criteria, or retrying with different context (`INFO-004`).
- Siblings are not notified; the failed result is indistinguishable in shape from any other result, only in content (`INFO-005`).
- The child stops at the point of failure and stays contained (`INFO-005`).
- Boundary (decision 0015): the escalation routing policy is operator tooling composed over the core directed-message primitive — its event is receiver-addressed (to the parent), so the parent sees it on its own stream whether or not the escalation channel is installed.

## Owns
- The upstream control channel from child to parent for renegotiation.

## Excludes
- Crash containment and failure surfacing, which this rides on — `INFO-005`.
- The parent-side remedies: re-decomposition — `INFO-010`.
- Pre-execution fan-out where criteria are fixed — `INFO-009`.
