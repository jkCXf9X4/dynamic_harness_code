---
id: INFO-022
type: info
title: Chat continuously while subagents run
summary: Operator messages keep flowing while subagents run, and a message sent mid-turn steers the root's current turn immediately
date: 2026-10-05
status: current
---

# Chat continuously while subagents run

- The operator's chat with the root stays live while the hierarchy below runs: running subagents never block message delivery (`INFO-017`, `INFO-014`).
- A message the operator sends while the root is mid-turn steers immediately: it reaches the current turn and can redirect running work.
- The root's responses stream back continuously instead of arriving only as a final result, pulled on demand through the artifact tiers (`INFO-006`).

## Owns
- Continuous operator messaging during a running hierarchy: delivery while mid-turn (steering) and streaming responses.

## Excludes
- The operator-to-root request-result door itself — `INFO-017`.
- Parent liveness that keeps the channels open — `INFO-014`.
- Artifact publication tiers the streaming rides on — `INFO-006`.
