---
id: INFO-022
type: info
title: Chat continuously while subagents run
summary: Operator messages keep flowing while subagents run; the chat loop is synchronous, so !steer is delivered between requirements via runtime.send
date: 2026-10-05
status: current
---

# Chat continuously while subagents run

- **Chat stays live**
  - Operator's chat with root stays live while hierarchy below runs.
  - Running subagents never block message delivery (`INFO-017`, `INFO-014`).
- **Mid-turn steering**
  - The chat loop is synchronous: `operator.run` blocks to settlement, so the human types `!steer` only between requirements.
  - `!steer` is delivered via `runtime.send` (framework primitive, decision 0015) to the named agent's event stream; it prints "steered <id>".
  - The target is a settled agent, so the message does not redirect a running turn on the chat path.
- **Streaming responses**
  - Root's responses stream back continuously, not only final result.
  - Pulled on demand through artifact tiers (`INFO-006`).

## Owns
- Continuous operator messaging during running hierarchy: delivery while mid-turn (steering) and streaming responses.

## Excludes
- Operator-to-root request-result door itself — `INFO-017`.
- Parent liveness keeping channels open — `INFO-014`.
- Artifact publication tiers streaming rides on — `INFO-006`.
- Demand-driven pump stepping that keeps delivery unblocked — `INFO-062`.
