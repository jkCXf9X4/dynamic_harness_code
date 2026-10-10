---
id: INFO-023
type: info
title: Ask the operator a question
summary: Any agent can ask the operator a question; the question routes up the parent chain and the answer returns to the asking agent
date: 2026-10-05
status: current
---

# Ask the operator a question

- **Any agent can ask**
  - Any agent, not just root, can ask operator a question.
  - Question routes up parent chain to root, crosses to operator (`INFO-014`).
- **Attribution and reply**
  - Operator sees question attributed to asking agent.
  - Answer routes back down same chain to asking agent.
- **One carve-out**
  - Operator invisible to inner agents, except this (`INFO-017`).
  - Boundary stays single door through root.
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
