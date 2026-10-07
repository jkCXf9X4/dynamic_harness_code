---
id: 0006
type: decision
title: "IMP-001 — INFO-048 partial reversal: event-stream consumption moves into the loop (placement, not discipline)"
date: 2026-10-07
status: accepted
---

# INFO-048 partial reversal — event-stream consumption moves into the loop

## Context

INFO-048 ruled that the runtime owns event-stream consumption: the driver
drains the agent's events (`LLMDriver._recent_context`), and consumed events
never come back. The reason for the original ruling was interpreter-level
locks and a private namespace — the runtime had to be the consumer because
agent code could not safely read its own stream.

IMP-001 (D1) moves the loop into the workspace: the agent *is* the loop and
reads its own events as ordinary data. The scoping question is whether this
reverses INFO-048's discipline or only its placement.

## Decision

**Partial reversal — placement, not discipline.** Event-stream *consumption*
moves into the loop (the agent's `__runner` reads its own stream as part of
its orchestration), but the *discipline* stays runtime-owned and unchanged:
FIFO order, at-most-once delivery, persist-before-execute (the boundary log,
INFO-049, remains the provenance backbone). `event_stream.py` itself is
unchanged — only the consumer changes.

The reason for the original ruling survives: interpreter-level locks and the
private namespace are no longer a constraint because the loop now runs *in*
the workspace, but the discipline (FIFO, at-most-once, persist-before-execute)
stays external so a degrading agent cannot corrupt the stream or the log.

## Rationale

The IMP mandates recording this partial reversal in a decision record. The
reversal is deliberate and bounded: consumption placement changes, discipline
does not. This preserves the guarantees that made INFO-048 correct (the
boundary log is the single provenance backbone; events are delivered at most
once in FIFO order) while removing the runtime-squeezed read model that was
the pain.

## Alternatives Considered

- **Full reversal (discipline moves into the loop too)** — a degrading agent
  could drop, reorder, or re-deliver events; the boundary log loses its
  guarantee. Rejected.
- **No reversal (runtime keeps consuming)** — the lossy-context pain stands;
  the agent still works blind on its own history. Rejected.

## Consequences

- `event_stream.py`: unchanged discipline (FIFO, at-most-once,
  persist-before-execute); only consumption moves into the loop.
- On adoption, INFO-051 is revised to state "event-stream consumption in-loop,
  discipline runtime-owned"; INFO-048's ruling is amended by this record.
- Per-step events flow through the boundary log (INFO-049) as before.