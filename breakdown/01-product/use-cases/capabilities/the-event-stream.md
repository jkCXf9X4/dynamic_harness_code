---
id: INFO-051
type: info
title: The event stream
summary: The runtime-owned stream of settled events arriving to an agent — handled outside the code-as-action-space so context and wakeups stay runtime-managed: no stream surface is reachable from agent code, settled values arrive as data between the agent's own actions, and registration is by held handle
date: 2026-10-06
status: current
---

# The event stream

- The event stream is the runtime-owned channel on which everything settling outside an agent — child completions, cancellations, timeouts — arrives to that agent; it is the boundary between the agent's code and the rest of the run.
- One settled child is one event: the event carries a frozen result tagged with the child that produced it — no arbitrary payloads, no live handles (`INFO-046`, `INFO-048`).
- The stream is handled outside the code-as-action-space — never drained or polled from agent code, and no stream surface is reachable from inside an action.
- That placement is what keeps context managed: the agent's context stays on the task — its namespace carries no event-loop plumbing, queue discipline, or interpreter-level locks (`INFO-048`, `INFO-050`).
- Wakeups stay runtime-managed: a blocked await resumes when its child settles (`INFO-031`), a registered callback runs between the agent's own actions (`INFO-033`, `INFO-039`) — the agent never runs the wakeup machinery itself.
- Settled values arrive as data between the agent's own actions; the callback executes in the parent's REPL, never concurrently (`INFO-033`, `INFO-046`).
- The REPL-side pull primitives, await and poll (`INFO-031`, `INFO-032`), act on child handles, never on the stream.
- Registration is by held handle: an agent registers its own stream, a child's via its spawn handle, or a peer's only via a wired channel (`INFO-018`).

## Owns
- The event stream as seen from agent code: what it is — the runtime-owned channel of settled events arriving to an agent — handled outside the code-as-action-space so context and wakeups stay runtime-managed, no draining or polling, settled values as data between actions, and handle-scoped registration.

## Excludes
- The settlement pattern the stream carries — one completion per settled child, at most once each — `INFO-046`.
- Where settled events execute — the parent's own REPL, never concurrently — `INFO-033`.
- The agent REPL the stream is kept out of — `INFO-050`.
- The resolution machinery — loop-side polling, typed intake, settlement discipline — `INFO-048`.
- The dispatch of settled completions between parent actions — `INFO-047`.
- The boundary log watching the stream from outside — `INFO-049`.
- The agent's own output stream that context-rot detection monitors — `INFO-021`.
- The operator-facing streaming of the root's responses — `INFO-022`.
- The host-facing API's outcome stream — `INFO-025`.
- The kernel commitment itself — the turn engine made real — stays with the execution-core contract, uncommitted: `INFO-037`.
