---
id: IMP-003
type: imp
title: Mixed wall-clock bases across caps, step start, and sleep deadline
summary: time.time and time.monotonic are mixed across the caps timeout, the step start, and the sleep deadline, so a wall-clock jump can trip or mask a cap
date: 2026-10-08
status: current
pb_exempt: true
---

# Mixed wall-clock bases across caps, step start, and sleep deadline

A scoped candidate, not implementation approval. It needs a decision record
and a task contract before code changes begin (change pipeline).

## Why — pain and evidence

- **Three wall-clock bases coexist.** The scoping brief (run
  `261008_105638_6a18`, §2 coupling point 6) and decision record `0007`
  (agent module separation) list the mix: `time.time` at the caps wall-clock
  check (`src/dhc/framework/caps.py:85`, `time.time() - started_ts >
  timeout_seconds`), the step start (`src/dhc/framework/loop.py:277`,
  `started_ts = time.time()`), and the settle timestamp
  (`src/dhc/framework/runtime.py:490`, `agent.settled_ts = time.time()`); while
  the sleep deadline uses `time.monotonic` (`src/dhc/framework/loop.py:553/557`,
  `deadline = time.monotonic() + seconds`).
- **A wall-clock jump can trip or mask a cap.** `time.time` is the wall
  clock: an NTP step, a DST change, or a manual clock edit moves it
  discontinuously. The caps wall-clock check compares a `time.time` delta
  against a timeout, so a backward jump can *mask* a real overrun (the cap
  stops tripping) and a forward jump can *trip* a cap that was not actually
  exceeded. `time.monotonic` is immune to this; the sleep deadline already
  uses it.
- **The refactor made the seam visible.** Decision record `0007` moved the
  caps predicate into `caps.py` and the step start into `loop.py`, so the two
  bases now sit in two modules that should agree on which clock a "step" and
  a "timeout" are measured against.

## The proposed shape

- **One base for durations, one for timestamps.** Measure all *durations*
  (step elapsed, caps wall-clock timeout, sleep remaining) on
  `time.monotonic`; keep `time.time` only for *wall-clock timestamps* that are
  reported or persisted (e.g. `settled_ts`), never for a delta that drives a
  cap.
- **A single clock seam.** A small named helper (e.g. `now_monotonic()` /
  `now_wall()`) or a module-level constant makes the base explicit at each
  call site, so a future change is one edit, not a hunt.
- **A test that a wall-clock jump does not trip a cap** (monkeypatch
  `time.time` to step forward/backward; assert the caps predicate, which now
  reads `time.monotonic`, is unaffected).

## What must change

| Module | Change |
|---|---|
| `src/dhc/framework/caps.py` | The wall-clock cap reads a `time.monotonic` delta (step start captured on the same base) instead of a `time.time` delta. |
| `src/dhc/framework/loop.py` | `started_ts` (line 277) captured on `time.monotonic` to match the caps predicate; the sleep deadline (lines 553/557) already on `time.monotonic` stays. |
| `src/dhc/framework/runtime.py` | `settled_ts` (line 490) stays a `time.time` wall-clock timestamp (reported, not a cap input) — documented as the one wall-clock use. |
| `tests/` (caps tests) | A wall-clock-jump test proving the caps predicate is monotonic-based and unaffected by a `time.time` step. |

## Containment

| Change goes wrong | What happens |
|---|---|
| A cap is left on `time.time` | The wall-clock-jump test fails loudly; the cap is not silently maskable/trippable |
| A reported timestamp is accidentally switched to monotonic | The timestamp is no longer a wall-clock value; a test asserting `settled_ts` is a wall-clock value catches it |

## Risks and open questions

- **Behavior parity.** The caps predicate must keep tripping at the same
  *elapsed* duration; only the base changes. A test that a real overrun still
  trips the cap (on the monotonic base) is required.
- **`settled_ts` consumers.** Anything that reads `settled_ts` as a wall-clock
  timestamp is unaffected; anything that diffs it against a monotonic value is
  a latent bug this change should surface.
- **Open.** Whether the clock seam is a helper in `caps.py`/`loop.py` or a
  shared `dhc` utility; whether `settled_ts` should be renamed to make its
  wall-clock role explicit.

## Owns
- The wall-clock base hazard: the `time.time`/`time.monotonic` mix across the
  caps timeout, the step start, and the sleep deadline, and their
  consolidation onto one base for durations.

## Excludes
- The `_MemoryBus` drain race — a sequenced follow-on to decision record
  `0007`, not this candidate.
- The stringly-typed event kinds (IMP-002) and the inert token fields
  (IMP-004).
- The ceiling-cap *defaults* (the values) — owned by `config.py`/`SafetyConfig`,
  not the clock base.
