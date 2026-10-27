---
id: INFO-023
type: info
title: Ask the operator a question
summary: Any agent can ask the operator a question; the question goes to the operator channel and the answer returns to the asking agent
date: 2026-10-05
status: current
---

# Ask the operator a question

- **Any agent can ask**
  - Any agent, not just root, can ask the operator a question.
  - The question goes to the operator channel, not up the parent chain (`INFO-014`).
- **Attribution and reply**
  - The operator sees the question attributed to the asking agent.
  - The answer is addressed to the asking agent, on its own stream.
- **One carve-out**
  - The operator is invisible to inner agents, except this channel (`INFO-017`).
  - Escalation is the only path that climbs the parent chain.
- **Asking is normal, not failure**
  - Escalation reports failed result to parent instead (`INFO-011`).
- **Boundary (decision `AD-009`)**
  - Question channel: operator tooling composed over core directed-message primitive.
  - Answer event receiver-addressed to asking agent.
  - Asker sees it on own stream regardless of channel.

## Owns
- Operator-question channel: any agent can ask, answer returns to asking agent.

## Excludes
- Operator-to-root request-result door this carves out of — `INFO-017`.
- Escalation of unreachable requirement — `INFO-011`.
- Agent-to-agent channels and rooms — `INFO-015`, `INFO-016`.
