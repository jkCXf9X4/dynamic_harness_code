---
id: INFO-045
type: info
title: Never drain the event stream
summary: Agent code never drains or polls the event stream — settled values arrive as data between actions, await and poll act on child handles, and registration is by held handle
date: 2026-10-06
status: current
---

# Never drain the event stream

- The event stream is never drained or polled from agent code — no stream surface is reachable from inside an action.
- Settled values arrive as data between the agent's own actions; the callback executes in the parent's REPL, never concurrently (`INFO-033`, `INFO-046`).
- The REPL-side pull primitives, await and poll (`INFO-031`, `INFO-032`), act on child handles, never on the stream.
- Registration is by held handle: an agent registers its own stream, a child's via its spawn handle, or a peer's only via a wired channel (`INFO-018`).

## Owns
- The event-stream boundary as seen from agent code: no draining or polling, settled values as data between actions, handle-scoped registration.

## Excludes
- Where settled events execute — the parent's own REPL, never concurrently — `INFO-033`.
- The settlement pattern this boundary serves — `INFO-046`.
- The boundary log watching the stream from outside — `INFO-049`.
- The resolution machinery — loop-side polling, typed intake, settlement discipline — `INFO-048`.
- The kernel commitment itself — the turn engine made real — stays with the execution-core contract, uncommitted: `INFO-037`.
