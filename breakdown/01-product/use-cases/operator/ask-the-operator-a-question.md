---
id: INFO-023
type: info
title: Ask the operator a question
summary: Any agent can ask the operator a question; the question routes up the parent chain and the answer returns to the asking agent
date: 2026-10-05
status: current
---

# Ask the operator a question

- Any agent, not just the root, can ask the operator a question: the question routes up the parent chain to the root and crosses to the operator (`INFO-014`).
- The operator sees the question attributed to the asking agent; the answer routes back down the same chain to the asking agent.
- This is the one carve-out to the operator's invisibility to inner agents — the boundary stays a single door through the root (`INFO-017`).
- Asking is a normal channel state, not a failure: an escalation reports a failed result to the parent instead (`INFO-011`).
- Boundary (decision AD-009): the question channel is operator tooling composed over the core directed-message primitive; the answer event is receiver-addressed (to the asking agent), so the asker sees it on its own stream regardless of the channel.

## Owns
- The operator-question channel: any agent can ask, and the answer returns to the asking agent.

## Excludes
- The operator-to-root request-result door this carves out of — `INFO-017`.
- Escalation of an unreachable requirement — `INFO-011`.
- Agent-to-agent channels and rooms — `INFO-015`, `INFO-016`.
