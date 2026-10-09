---
id: IMP-002
type: imp
title: Stringly-typed event kinds in the state snapshot
summary: StateWriter matches event kinds by string literals instead of the EventKind enum, so a renamed or new kind silently drops from the snapshot
date: 2026-10-08
status: current
pb_exempt: true
---

# Stringly-typed event kinds in the state snapshot

A scoped candidate, not implementation approval. It needs a decision record
and a task contract before code changes begin (change pipeline).

## Why — pain and evidence

- **The snapshot path re-derives event identity by string.**
  `src/dhc/ui/state.py` (`StateWriter.on_event`, lines 364–399) converts
  each event's kind with `kind.value if hasattr(kind, "value") else str(kind)`
  and then branches on **string literals**: `if kind_value == "report"`
  (line 369), `elif kind_value == "failure"` (line 379),
  `elif kind_value == "escalation"` (line 386). The rest of the codebase
  speaks the `EventKind` enum (`src/dhc/data/models.py`); only this consumer
  speaks strings.
- **A rename or a new kind silently drops.** If an `EventKind` member is
  renamed, or a new kind is added that the snapshot should record, nothing
  fails: the literal no longer matches, the event is skipped, and the
  snapshot view-model (`AgentNode`) quietly loses that history. There is no
  compile-time or test-time link between the enum and the snapshot's
  branches.
- **The refactor made the seam visible.** Decision record `0007` (agent
  module separation) moved the loop/caps/integrity/context concerns out of
  `runtime.py` and listed this as an open hazard; the stringly-typed branch is
  the one place where the event contract is duplicated by hand.

## The proposed shape

- **Match on the enum, not on strings.** `on_event` branches on
  `EventKind` members directly (with a safe fallback for non-enum kinds), so
  the snapshot's recognized kinds are the enum's members — one definition,
  no second copy.
- **Make the mapping explicit and testable.** A small
  `EventKind → snapshot event_type` mapping (or a per-kind handler table)
  lives next to the enum or in `state.py` as a named constant, so "which
  kinds does the snapshot record" is a readable, diffable fact.
- **A test per recognized kind** (and one asserting an unrecognized kind is
  handled by the documented fallback, not silently lost).

## What must change

| Module | Change |
|---|---|
| `src/dhc/ui/state.py` | `on_event` branches on `EventKind` members (or an explicit mapping) instead of string literals; fallback behavior for unknown kinds documented and preserved. |
| `tests/` (state tests) | One test per recognized kind; one test for the unknown-kind fallback. |

## Containment

| Change goes wrong | What happens |
|---|---|
| A kind is renamed without updating the mapping | The mapping is the single source; the per-kind test fails loudly instead of the snapshot silently dropping events |
| A new kind is added | It is recorded only if added to the mapping — a visible, reviewable decision, not an accident |

## Risks and open questions

- **Behavior parity.** The current string branches are the only definition of
  "which kinds the snapshot records"; the mapping must reproduce them exactly
  (report/failure/escalation today) or the snapshot's output changes.
- **Non-enum kinds.** `on_event` already tolerates non-enum kinds via
  `str(kind)`; the fallback must keep that tolerance.
- **Open.** Whether the mapping lives in `state.py` or beside `EventKind` in
  `data/models.py`; whether unrecognized kinds should be recorded verbatim
  (today they are dropped).

## Owns
- The event-kind → snapshot mapping hazard: the stringly-typed branches in
  `StateWriter.on_event` and their replacement by an enum-driven, tested
  mapping.

## Excludes
- The event-stream discipline (FIFO, at-most-once, persist-before-execute) —
  `INFO-048`/`INFO-051`, unchanged.
- The `_MemoryBus` drain race — a sequenced follow-on to decision record
  `0007`, not this candidate.
- The wall-clock base mix (IMP-003) and the inert token fields (IMP-004).
