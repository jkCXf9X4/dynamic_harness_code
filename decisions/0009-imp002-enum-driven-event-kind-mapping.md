---
id: 0009
type: decision
title: "IMP-002 — Enum-driven event-kind mapping in the state snapshot"
date: 2026-10-09
status: accepted
---

# Enum-driven event-kind mapping — `StateWriter.on_event` branches on `EventKind`, not strings

## Context

IMP-002 (`breakdown/06-evolution/selected/stringly-typed-event-kinds-in-the-state-snapshot.md`)
flags that the operator state snapshot re-derives event identity by string.
`src/dhc/agent/state.py` (`StateWriter.on_event`, lines 364–399) converts each
event's kind with `kind.value if hasattr(kind, "value") else str(kind)` and
then branches on **string literals**: `if kind_value == "report"`,
`elif kind_value == "failure"`, `elif kind_value == "escalation"`. The rest of
the codebase speaks the `EventKind` enum (`src/dhc/data/models.py`); only this
consumer speaks strings.

The hazard: if an `EventKind` member is renamed, or a new kind is added that
the snapshot should record as terminal, nothing fails — the literal no longer
matches, the event falls to the `else` (activity) branch, and the snapshot
view-model quietly loses the terminal classification. There is no compile-time
or test-time link between the enum and the snapshot's branches.

**Key finding (verified against source):** the `"report"` and `"failure"`
branches are **dead code**. `EventKind` has no member with value `"report"` or
`"failure"`, and the typed bus validates `Event.kind: EventKind`
(`data/models.py`), so a raw `"report"`/`"failure"` event cannot be
constructed or published. The only *live* terminal kind is
`EventKind.escalation` (emitted at `ui/communication.py:235`). The reachable
behavior today is therefore: `escalation` → terminal (force snapshot); every
other kind → activity (throttled snapshot). Removing the two dead string
branches changes no observable output.

## Decision

**Match on the `EventKind` member, not on its string value, via an explicit
terminal table.** A module-level `TERMINAL_EVENT_KINDS: dict[EventKind, str]`
in `state.py` is the single source of truth for "which kinds the snapshot
records as terminal." `on_event` routes a kind to the terminal path **iff**
`isinstance(kind, EventKind) and kind in TERMINAL_EVENT_KINDS`; everything
else (other enum kinds *and* non-enum kinds) is recorded as activity.

**Fail-loudly choice: never drop at runtime; fail loudly at import time and
test time.** The snapshot is a peripheral view-model whose contract is "must
never crash a snapshot" (module docstring), so `on_event` does **not** raise
on an unknown kind — it records it as activity (the documented fallback, which
also preserves the pre-existing tolerance for non-enum kinds via `str(kind)`).
Loudness is instead guaranteed at two earlier seams:

1. **Import time (rename of a member *name*).** `TERMINAL_EVENT_KINDS` is
   keyed by `EventKind` *member* (`EventKind.escalation`), not by string.
   Renaming the member (e.g. `escalation` → `escalated`) without updating the
   table makes `state.py` reference a non-existent member → `AttributeError`
   at import. A hard, immediate failure — not a silent drop.
2. **Test time (new kind / reclassification).** Per-kind tests publish every
   `EventKind` member and assert each is recorded (no silent drop); a pinned
   terminal-set test asserts `set(TERMINAL_EVENT_KINDS) == {EventKind.escalation}`
   so promoting a new kind to terminal is a visible, reviewable test change,
   not an accident.

A rename of a member's *value* (e.g. `escalation = "escalation"` →
`"escalated"`) is safe: the table is keyed by member, so routing is
unaffected; only the recorded `event_type` string changes, which is a visible
diff in the table's value.

## Rationale

1. **One definition, no second copy.** The terminal set is the enum's members
   as named in `TERMINAL_EVENT_KINDS` — the snapshot's recognized kinds are a
   readable, diffable fact next to the code that uses them, not a hand-duplicated
   set of string literals.
2. **The view-model must not crash the snapshot.** Raising in `on_event` on an
   unknown kind would let a single unrecognized event take down the operator
   overview — the exact failure mode the module is designed to avoid. Recording
   as activity (throttled) is the safe, non-dropping fallback; loudness is
   moved to the seams where it cannot hurt the live snapshot (import + tests).
3. **Behavior parity is preserved for all reachable inputs.** The only live
   terminal kind (`escalation`) still records `{"event": "escalation",
   "issue": ...}` and forces a snapshot; every other reachable kind still
   records as activity. The two dead branches (`report`/`failure`) are removed
   because they are unreachable (no `EventKind` member, typed bus) — removing
   them changes no observable output and eliminates the stringly-typed hazard.
4. **The mapping is the single source of truth.** Per the IMP-002 containment
   table: a rename without updating the mapping fails loudly (import error)
   instead of silently dropping; a new kind is recorded only if added to the
   mapping — a visible, reviewable decision.

## Changes made

- `src/dhc/agent/state.py` —
  - import `EventKind` from `..data.models`.
  - add module-level `TERMINAL_EVENT_KINDS: dict[EventKind, str]`
    (`{EventKind.escalation: "escalation"}`) and `_terminal_record(kind,
    agent_id, payload)` (enum-keyed record builder).
  - `on_event` now branches on `isinstance(kind, EventKind) and kind in
    TERMINAL_EVENT_KINDS` (terminal) vs. activity fallback; the three string
    branches (`"report"`/`"failure"`/`"escalation"`) are replaced. The
    `report`/`failure` branches are removed as dead code (see Context).
- `tests/agent/test_state.py` — additive per-kind + contract tests (below).
  No existing test is modified or weakened.

## Verification

Full suite green (see final count in the run report; baseline 483 passed at
main `5fe29aa`).
New tests, all in `tests/agent/test_state.py`:

1. `test_every_event_kind_is_recorded_not_dropped` — publishes **every**
   `EventKind` member through the bus and asserts each yields a line in
   `events.jsonl` (terminal or activity). This is the direct "a renamed/new
   kind cannot silently drop" proof: any kind that fell through unrecorded
   fails the test.
2. `test_terminal_kind_escalation_forces_snapshot_and_records_issue` —
   per-kind terminal test: `EventKind.escalation` records
   `{"event": "escalation", "issue": ...}` and forces a snapshot.
3. `test_activity_kind_records_event_type_and_throttles` — per-kind activity
   test: `EventKind.turn_started` records `{"event": "activity",
   "event_type": "turn_started", ...}`.
4. `test_terminal_table_keys_are_real_event_kinds` — asserts
   `set(TERMINAL_EVENT_KINDS) <= set(EventKind)` (a stale/renamed member name
   in the table is caught; the import-time `AttributeError` is the loud path).
5. `test_terminal_set_is_explicit` — pins
   `set(TERMINAL_EVENT_KINDS) == {EventKind.escalation}` so promoting a new
   kind to terminal is a visible, reviewable test change.
6. `test_renamed_terminal_member_fails_loudly_not_silently` — proves the
   rename-loudness mechanism: the table is member-keyed (every key is a live
   `EventKind` member), and referencing a renamed-away member name is a hard
   `AttributeError` at construction time — the import-time loud path, not a
   silent drop.

## Alternatives Considered

- **Raise in `on_event` on an unknown/renamed kind (fail loudly at runtime).**
  Most literal reading of "fail loudly," but it lets one unrecognized event
  crash the operator snapshot — violating the view-model's "must never crash a
  snapshot" contract. Rejected in favor of never-drop at runtime + loud at
  import/test time.
- **Keep the `"report"`/`"failure"` string branches as a non-enum fallback.**
  Preserves the dead branches and perpetuates the stringly-typed hazard this
  decision removes. They are unreachable (no `EventKind` member, typed bus),
  so keeping them adds risk with no behavior. Rejected.
- **Live the mapping beside `EventKind` in `data/models.py`.** The IMP leaf
  leaves this open. Placing it in `state.py` keeps the snapshot's policy
  ("which kinds are terminal *for the snapshot*") with its only consumer and
  avoids coupling the data model to a peripheral view-model concern. Chosen
  for locality; the table is a named, diffable constant either way.

## Consequences

- A renamed terminal member name is an import-time `AttributeError` (loud),
  never a silent drop; a renamed member value is a visible table diff.
- A new `EventKind` is recorded as activity by default (never dropped); making
  it terminal is a deliberate, test-pinned change.
- The snapshot's reachable output is byte-identical to before for all live
  kinds; the two dead `report`/`failure` branches are gone.
- The event-stream discipline (FIFO, at-most-once, persist-before-execute —
  INFO-048/051) and the `_MemoryBus` drain race are untouched (out of scope per
  the IMP-002 leaf).
