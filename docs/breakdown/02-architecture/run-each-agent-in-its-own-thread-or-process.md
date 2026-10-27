---
id: INFO-038
type: info
title: Agent execution placement
summary: Every agent runs its code in the runtime process today; per-agent thread or process isolation is the future hardening target
date: 2026-10-06
status: current
---

# Agent execution placement

- Every agent — root, middle, or worker — runs its code in the runtime process today, not in a separate process.
- A crash or hang is contained to the agent's workspace; the runtime process survives (`INFO-005`).
- Per-agent persistent REPLs (`INFO-050`) ride on this in-process placement.
- **Scope note.** Per-agent thread or process isolation is the hardening target, not the current state (`IMP-001`).

## Owns
- The agent concurrency-placement fact: in-process today, per-agent thread or process isolation as the hardening target.

## Excludes
- The crash-containment contract this placement delivers — `INFO-005`.
- The container deployment boundary around all agents — `INFO-008`.
- The child-REPL isolation contract instance this places — `INFO-050`.
