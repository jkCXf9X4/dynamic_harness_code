---
id: 0003
type: decision
title: "IMP-001 D3 — Bounded-sync vs yield-async op split"
date: 2026-10-07
status: accepted
---

# D3 — Bounded-sync vs yield-async op split

## Context

Blocking supervision burns wall-clock: `await_` (INFO-031) blocks the parent's
worker thread; a slow child consumes the parent's turn/timeout budget for the
entire wait. The trampoline (D1) introduces a yield vocabulary, and the
scoping question is which operations are direct workspace calls and which are
`yield` requests serviced by the pump.

## Decision

**Direct workspace calls** for bounded, synchronous operations:
`run_block(code)`, `inbox.drain`, `messenger.send`, guardrail/budget edits.

**`yield` requests** only for indefinite or off-thread operations, serviced by
the pump: `yield Await(handle)`, `yield Poll(handle)`, `yield Sleep(t)`, and
completion wakeups. A parent can `yield Await(child)` **without consuming step
budget** — this is the trampoline's core win over blocking `await_` today.

## Rationale

The split keeps the generator simple to author, keeps the pump's contract tiny
(one small request vocabulary), and eliminates the parent-thread-starvation
failure of blocking `await_` (INFO-031) — waiting on a child no longer
consumes a parent's step budget. Bounded ops stay synchronous because they
cannot hang the step; only indefinite/off-thread ops need the pump's
park/resume machinery.

## Alternatives Considered

- **Yield everything** — an over-typed request vocabulary; harder to author
  and to service. Rejected.
- **Call everything directly** — blocking supervision burns budgets again;
  the parent-thread-starvation failure returns. Rejected.

## Consequences

- The pump classifies each yield as settle/wait/sleep and services it
  (park/resume for `Await`/`Poll`, timer for `Sleep`, completion wakeups).
- `yield Await(child)` does not consume the parent's step budget; a
  slow-child test must prove the parent thread is not starved.
- Whether `yield Await` replaces `await_` at the surface or coexists is an
  open question tracked in the IMP's risks; the default loop keeps `await_`
  working for backward compatibility.