---
id: INFO-038
type: info
title: Run each agent in its own thread or process
summary: Every agent executes in its own thread-or-process unit, isolated from the runtime process and from every other agent
date: 2026-10-06
status: current
---

# Run each agent in its own thread or process

- Every agent — root, middle, or worker — runs in its own thread or process, separate from the runtime process and from every other agent.
- A crash or hang takes down the agent's thread-or-process unit only; the runtime process survives (`INFO-005`).
- Per-agent persistent REPLs (`INFO-050`) and per-action execution isolation ride on this placement.

## Owns
- The agent concurrency-placement design: one thread-or-process execution unit per agent, isolated from the runtime and from every other agent.

## Excludes
- The crash-containment contract this placement delivers — `INFO-005`.
- The container security boundary around all agents — `INFO-008`.
- The child-REPL isolation contract instance this places — `INFO-050`.
