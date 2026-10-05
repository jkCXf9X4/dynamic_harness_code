---
id: INFO-026
type: info
title: Compress a running agent's context
summary: Collapse accumulated context into a summary that leans on persisted artifacts, the committed remedy for detected context rot short of re-decomposition
date: 2026-10-05
status: draft
---

# Compress a running agent's context

- The pain: long-running and re-decomposing agents accumulate context; detection exists (`INFO-021`) but its exclusions defer the response, so detection has today no committed remedy short of re-decomposition (`INFO-010`) or escalation (`INFO-011`).
- The candidate: compression — collapse older context into a summary that leans on the persisted artifacts (`INFO-006`), so detail stays recoverable on demand.

## Owns
- The context-compression candidate: the committed remedy for detected rot short of re-decomposition.

## Excludes
- Detection of the rot that triggers it — `INFO-021`.
- Response by re-decomposition — `INFO-010`.
- Escalation — `INFO-011`.
- The artifact tiers compression leans on — `INFO-006`.
