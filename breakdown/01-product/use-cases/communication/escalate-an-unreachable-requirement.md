---
id: INFO-011
type: info
title: Escalate an unreachable requirement
summary: A child whose acceptance criteria prove unreachable reports a failed result with a reason and the parent re-allocates
date: 2026-10-05
status: current
---

# Escalate an unreachable requirement

- **Failed result, not partial success.** Child with unreachable acceptance criteria reports a failed result carrying the reason (`INFO-005`).
- **Escalation travels upstream only** (`INFO-004`).
  - Parent re-allocates: re-decompose, relax criteria, or retry with different context.
- **Sibling notification** (`INFO-005`).
  - Siblings are not notified.
  - Failed result is indistinguishable in shape from any other result, only in content.
- Child stops at point of failure, stays contained (`INFO-005`).
- **Boundary (decision AD-009).** Escalation routing policy is operator tooling composed over the core directed-message primitive.
  - Event is receiver-addressed to the parent.
  - Parent sees event on its own stream, whether or not the escalation channel is installed.

## Owns
- Upstream control channel from child to parent, for renegotiation.

## Excludes
- Crash containment and failure surfacing, which this rides on — `INFO-005`.
- Parent-side remedy: re-decomposition — `INFO-010`.
- Pre-execution fan-out where criteria are fixed — `INFO-009`.
