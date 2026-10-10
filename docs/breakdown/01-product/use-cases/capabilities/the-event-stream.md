---
id: INFO-051
type: info
title: The event stream
summary: The runtime-owned stream of settled events arriving to an agent — per AD-006, consumption is the agent's (in-loop, read as ordinary data) while the discipline (FIFO, at-most-once, persist-before-execute) stays runtime-owned, and registration is by held handle
date: 2026-10-06
status: current
---

# The event stream

- **Runtime-owned arrival channel**
  - Everything settling outside an agent arrives on it: child completions, cancellations, timeouts.
  - Boundary between agent's code and rest of run.
- **One settled child, one event**
  - Event carries frozen result tagged with child producing it.
  - No arbitrary payloads, no live handles (`INFO-046`, `INFO-048`).
- **Consumption is agent's**
  - Per `AD-006`, agent's `__runner` reads own stream as ordinary data, part of its orchestration (in-loop).
- **Discipline stays runtime-owned**
  - FIFO order, at-most-once delivery, persist-before-execute.
  - Degrading agent cannot corrupt stream or boundary log (`INFO-048`, `INFO-049`).
- **Context stays managed**
  - Agent's context stays on task.
  - Namespace carries no queue discipline or interpreter-level locks, only stream it reads (`INFO-048`, `INFO-050`).
- **Wakeups runtime-managed**
  - Blocked await resumes when its child settles (`INFO-031`).
  - Registered callback runs between agent's own actions (`INFO-033`, `INFO-039`).
  - Agent never runs wakeup machinery itself.
- **Settled values arrive as data**
  - Arrive between agent's own actions.
  - Callback executes in parent's REPL, never concurrently (`INFO-033`, `INFO-046`).
- **Pull primitives act on child handles**
  - REPL-side pull primitives, await and poll (`INFO-031`, `INFO-032`), act on child handles, never on stream.
- **Registration by held handle**
  - Agent registers own stream.
  - Child's via its spawn handle.
  - Peer's only via wired channel (`INFO-018`).

## Owns
- Event stream as seen from agent code.
  - Runtime-owned channel of settled events arriving to agent.
  - Consumed in-loop by agent as ordinary data.
  - Discipline (FIFO, at-most-once, persist-before-execute) runtime-owned.
  - Settled values as data.
  - Handle-scoped registration.

## Excludes
- Settlement pattern stream carries: one completion per settled child, at most once each — `INFO-046`.
- Where settled events execute: parent's own REPL, never concurrently — `INFO-033`.
- Agent REPL stream kept out of — `INFO-050`.
- Resolution machinery: loop-side polling, typed intake, settlement discipline — `INFO-048`.
- Dispatch of settled completions between parent actions — `INFO-047`.
- Boundary log watching stream from outside — `INFO-049`.
- Agent's own output stream context-rot detection monitors — `INFO-021`.
- Operator-facing streaming of root's responses — `INFO-022`.
- Host-facing API's outcome stream — `INFO-025`.
- Kernel commitment itself: turn engine made real — `INFO-037`.
