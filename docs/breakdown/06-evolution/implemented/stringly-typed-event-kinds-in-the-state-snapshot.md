---
id: IMP-002
type: imp
title: Stringly-typed event kinds in the state snapshot
summary: StateWriter matches event kinds by string literals, not the EventKind enum. Renamed or new kind silently drops from the snapshot
date: 2026-10-08
status: current
pb_exempt: true
---

# Stringly-typed event kinds in the state snapshot

Scoped candidate, not implementation approval. Needs decision record and task contract before code changes begin (change pipeline).

## Why — pain and evidence

- **The snapshot path re-derives event identity by string.**
  - `src/dhc/ui/state.py` (`StateWriter.on_event`, lines 364–399) converts each event's kind with `kind.value if hasattr(kind, "value") else str(kind)`.
  - Branches then test string literals: `if kind_value == "report"` (line 369), `elif kind_value == "failure"` (line 379), `elif kind_value == "escalation"` (line 386).
  - Rest of codebase speaks the `EventKind` enum (`src/dhc/data/models.py`).
  - Only this consumer speaks strings.

- **A rename or a new kind silently drops.**
  - Renamed `EventKind` member, or new kind the snapshot should record: nothing fails.
  - Literal no longer matches. Event is skipped.
  - Snapshot view-model (`AgentNode`) quietly loses that history.
  - No compile-time or test-time link between the enum and the snapshot's branches.

- **The refactor made the seam visible.**
  - Decision record `IMD-001` (agent module separation) moved the loop/caps/integrity/context concerns out of `runtime.py`.
  - It listed this as an open hazard.
  - The stringly-typed branch is the one place where the event contract is duplicated by hand.

## The proposed shape

- **Match on the enum, not on strings.**
  - `on_event` branches on `EventKind` members directly, with safe fallback for non-enum kinds.
  - Snapshot's recognized kinds then equal the enum's members.
  - One definition, no second copy.

- **Make the mapping explicit and testable.**
  - Small mapping from `EventKind` to snapshot `event_type` (or per-kind handler table).
  - It lives next to the enum or in `state.py` as a named constant.
  - "Which kinds does the snapshot record" then becomes a readable, diffable fact.

- **A test per recognized kind.**
  - Plus one test: unrecognized kind is handled by the documented fallback, not silently lost.

## What must change

- `src/dhc/ui/state.py`
  - `on_event` branches on `EventKind` members (or an explicit mapping), not string literals.
  - Fallback behavior for unknown kinds documented and preserved.
- `tests/` (state tests)
  - One test per recognized kind.
  - One test for the unknown-kind fallback.

## Containment

- **A kind is renamed without updating the mapping.**
  - Mapping is the single source.
  - Per-kind test fails loudly instead of the snapshot silently dropping events.
- **A new kind is added.**
  - Recorded only if added to the mapping.
  - Visible, reviewable decision, not an accident.

## Risks and open questions

- **Behavior parity.**
  - Current string branches are the only definition of "which kinds the snapshot records".
  - Mapping must reproduce them exactly (report/failure/escalation today), or the snapshot's output changes.

- **Non-enum kinds.**
  - `on_event` already tolerates non-enum kinds via `str(kind)`.
  - Fallback must keep that tolerance.

- **Open.**
  - Mapping lives in `state.py` or beside `EventKind` in `data/models.py`: open.
  - Whether unrecognized kinds should be recorded verbatim: open. Today they are dropped.

## Owns

- **Event-kind to snapshot mapping hazard.**
  - The stringly-typed branches in `StateWriter.on_event`.
  - Their replacement by an enum-driven, tested mapping.

## Excludes

- Event-stream discipline (FIFO, at-most-once, persist-before-execute), `INFO-048`/`INFO-051`: unchanged.
- The `_MemoryBus` drain race, sequenced follow-on to decision record `IMD-001`, not this candidate.
- Wall-clock base mix (IMP-003), inert token fields (IMP-004).
