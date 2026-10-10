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
- Working state lives in the agent's persistent REPL between actions; artifacts remain the durable medium for findings that cross agents or must outlive them (`INFO-050`).

## Motivation

Agents must share findings without polluting each other's context (`INFO-001`,
`INFO-012`), and whatever crosses the mesh must be immutable and verifiable
(`INFO-001`). The artifact protocol is how the architecture delivers both
promises — content address, disclosure tiers, one publish event — with the
vocabulary framework-owned and the medium in operator tooling (`AD-008`).

## Owns
- The artifact-driven communication and progressive-disclosure contract.

## Excludes
- The sandbox that executes the persisted code — `INFO-002`.
- The decomposition flow that passes artifact IDs — `INFO-004`.
