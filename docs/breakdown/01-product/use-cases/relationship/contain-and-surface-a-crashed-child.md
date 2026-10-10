---
id: INFO-005
type: info
title: Contain and surface a crashed child
summary: A crashed child is contained and never takes down siblings or the parent; it surfaces as a failed result
date: 2026-10-05
status: current
---

# Contain and surface a crashed child

- Crashed child is contained, never takes down a sibling or the parent (`INFO-001`).
- **Crash surfaces to the parent as a failed result** (`INFO-032`).
  - One distinguishable terminal state among completed, failed, cancelled, timeout.

## Owns
- Crash containment and failure surfacing.

## Excludes
- Retry or re-decomposition policy after a failure — `INFO-004`.
- The action loop that may crash — `INFO-002`.
