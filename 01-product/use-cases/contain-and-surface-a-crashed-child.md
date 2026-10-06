---
id: INFO-005
type: info
title: Contain and surface a crashed child
summary: A crashed child stays contained in its own thread and surfaces as a failed result to its parent
date: 2026-10-05
status: current
---

# Contain and surface a crashed child

- A crashed child is contained and never takes down a sibling or the parent (`INFO-001`).
- The crash surfaces to the parent as a failed result — one distinguishable terminal state among completed, failed, cancelled, and timeout (`INFO-032`).

## Owns
- Crash containment and failure surfacing.

## Excludes
- Retry or re-decomposition policy after a failure — `INFO-004`.
- The action loop that may crash — `INFO-002`.
