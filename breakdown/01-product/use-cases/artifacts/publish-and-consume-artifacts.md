---
id: INFO-006
type: info
title: Publish and consume artifacts
summary: Findings persist as immutable content-addressed artifacts that consumers pull headline-summary-report on demand
date: 2026-10-05
status: current
---

# Publish and consume artifacts

- **Immutable persistence**
  - Findings, results, every action's code persist as immutable, content-addressed artifacts (`INFO-001`).
- **Tiered disclosure**
  - Parents receive summaries plus artifact IDs.
  - Consumers pull tiers on demand: headline, then summary, then report.
- **Working state vs durable medium**
  - Working state lives in agent's persistent REPL between actions (`INFO-050`).
  - Artifacts remain durable medium for findings crossing agents or outliving them (`INFO-050`).

## Motivation

- Agents must share findings without polluting each other's context (`INFO-001`, `INFO-012`).
- Whatever crosses mesh must be immutable and verifiable (`INFO-001`).
- Artifact protocol delivers both promises: content address, disclosure tiers, one publish event.
- Vocabulary stays framework-owned. Medium stays in operator tooling (`AD-008`).

## Owns
- Artifact-driven communication and progressive-disclosure contract.

## Excludes
- Sandbox executing persisted code — `INFO-002`.
- Decomposition flow passing artifact IDs — `INFO-004`.
