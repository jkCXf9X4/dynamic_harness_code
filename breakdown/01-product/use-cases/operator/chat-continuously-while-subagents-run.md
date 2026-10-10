---
id: INFO-022
type: info
title: Chat continuously while subagents run
summary: Operator messages keep flowing while subagents run, and a message sent mid-turn steers the root's current turn immediately
date: 2026-10-05
status: current
---

# Chat continuously while subagents run

- **Chat stays live**
  - Operator's chat with root stays live while hierarchy below runs.
  - Running subagents never block message delivery (`INFO-017`, `INFO-014`).
- **Mid-turn steering**
  - Message sent while root mid-turn steers immediately.
  - Reaches current turn, can redirect running work.
- **Streaming responses**
  - Root's responses stream back continuously, not only final result.
  - Pulled on demand through artifact tiers (`INFO-006`).

## Owns
- Continuous operator messaging during running hierarchy: delivery while mid-turn (steering) and streaming responses.

## Excludes
- Operator-to-root request-result door itself — `INFO-017`.
- Parent liveness keeping channels open — `INFO-014`.
- Artifact publication tiers streaming rides on — `INFO-006`.
