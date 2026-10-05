---
id: INFO-006
type: info
title: Publish and consume artifacts
summary: Findings persist as immutable content-addressed artifacts that consumers pull headline-summary-report on demand
date: 2026-10-05
status: current
---

# Publish and consume artifacts

- Findings, results, and every action's code persist as immutable, content-addressed artifacts (`INFO-001`).
- Parents receive summaries plus artifact IDs; consumers pull headline → summary → report tiers on demand.
- State lives in artifacts, never in agent memory or container memory; every action runs in a fresh interpreter.

## Owns
- The artifact-driven communication and progressive-disclosure contract.

## Excludes
- The sandbox that executes the persisted code — `INFO-002`.
- The decomposition flow that passes artifact IDs — `INFO-004`.
