---
id: IMP-003
type: imp
title: Mixed wall-clock bases across caps, step start, and sleep deadline
summary: time.time and time.monotonic mix across the caps timeout, the step start, and the sleep deadline. A wall-clock jump can trip or mask a cap
date: 2026-10-08
status: current
pb_exempt: true
---

# Mixed wall-clock bases across caps, step start, and sleep deadline

Scoped candidate, not implementation approval. Needs decision record and task contract before code changes begin (change pipeline).

## Why — pain and evidence

- **Three wall-clock bases coexist.**
  - Scoping brief (run `261008_105638_6a18`, §2 coupling point 6) and decision record `IMD-001` (agent module separation) list the mix.
  - Caps wall-clock check: `src/dhc/framework/caps.py:85`, `time.time() - started_ts > timeout_seconds`.
  - Step start: `src/dhc/framework/pump.py:277`, `started_ts = time.time()`.
  - Settle timestamp: `src/dhc/framework/runtime.py:490`, `agent.settled_ts = time.time()`.
  - Sleep deadline uses `time.monotonic`: `src/dhc/framework/pump.py:553/557`, `deadline = time.monotonic() + seconds`.

- **A wall-clock jump can trip or mask a cap.**
  - `time.time` is the wall clock: an NTP step, a DST change, or a manual clock edit moves it discontinuously.
  - The caps wall-clock check compares a `time.time` delta against a timeout.
  - Backward jump can *mask* a real overrun (the cap stops tripping).
  - Forward jump can *trip* a cap that was not actually exceeded.
  - `time.monotonic` is immune to this; the sleep deadline already uses it.

- **The refactor made the seam visible.**
  - Decision record `IMD-001` moved the caps predicate into `caps.py` and the step start into `loop.py`.
  - The two bases now sit in two modules.
  - The modules should agree on which clock a "step" and a "timeout" are measured against.

## The proposed shape

- **One base for durations, one for timestamps.**
  - Measure all *durations* (step elapsed, caps wall-clock timeout, sleep remaining) on `time.monotonic`.
  - Keep `time.time` only for *wall-clock timestamps* that are reported or persisted (e.g. `settled_ts`).
  - Never for a delta that drives a cap.

- **A single clock seam.**
  - Small named helper (e.g. `now_monotonic()` / `now_wall()`) or a module-level constant makes the base explicit at each call site.
  - A future change is then one edit, not a hunt.

- **A test that a wall-clock jump does not trip a cap.**
  - Monkeypatch `time.time` to step forward/backward.
  - Assert the caps predicate, which now reads `time.monotonic`, is unaffected.

## What must change

- `src/dhc/framework/caps.py`
  - Wall-clock cap reads a `time.monotonic` delta (step start captured on the same base), not a `time.time` delta.
- `src/dhc/framework/pump.py`
  - `started_ts` (line 277) captured on `time.monotonic` to match the caps predicate.
  - Sleep deadline (lines 553/557) already on `time.monotonic` stays.
- `src/dhc/framework/runtime.py`
  - `settled_ts` (line 490) stays a `time.time` wall-clock timestamp (reported, not a cap input).
  - Documented as the one wall-clock use.
- `tests/` (caps tests)
  - Wall-clock-jump test proves the caps predicate is monotonic-based and unaffected by a `time.time` step.

## Containment

- **A cap is left on `time.time`.**
  - Wall-clock-jump test fails loudly.
  - The cap is not silently maskable/trippable.
- **A reported timestamp is accidentally switched to monotonic.**
  - The timestamp is no longer a wall-clock value.
  - A test asserting `settled_ts` is a wall-clock value catches it.

## Risks and open questions

- **Behavior parity.**
  - Caps predicate must keep tripping at the same *elapsed* duration; only the base changes.
  - A test that a real overrun still trips the cap (on the monotonic base) is required.

- **`settled_ts` consumers.**
  - Anything that reads `settled_ts` as a wall-clock timestamp is unaffected.
  - Anything that diffs it against a monotonic value is a latent bug this change should surface.

- **Open.**
  - Clock seam: helper in `caps.py`/`loop.py` or a shared `dhc` utility: open.
  - Whether `settled_ts` should be renamed to make its wall-clock role explicit: open.

## Owns

- **Wall-clock base hazard.**
  - The `time.time`/`time.monotonic` mix across the caps timeout, the step start, and the sleep deadline.
  - Their consolidation onto one base for durations.

## Excludes

- The `_MemoryBus` drain race, sequenced follow-on to decision record `IMD-001`, not this candidate.
- Stringly-typed event kinds (IMP-002), inert token fields (IMP-004).
- Ceiling-cap *defaults* (the values), owned by `config.py`/`SafetyConfig`, not the clock base.
