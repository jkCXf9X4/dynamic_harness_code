---
id: 0010
type: decision
title: "H-04 — Single monotonic time base for all duration comparisons (IMP-003)"
date: 2026-10-09
status: accepted
---

# H-04 — One monotonic time base for the wall-clock ceiling

## Context

The wall-clock ceiling chain mixed two clocks. The origin timestamp
`started_ts` was set with `time.time()` at pump start
(`src/dhc/agent/loop.py:278`) and the ceiling's "now" side was
`time.time()` inside the predicate (`src/dhc/agent/caps.py:192`), while the
parked-time credit measured by `service_await`/`service_sleep` used
`time.monotonic()` (`src/dhc/agent/loop.py:593-631`). Decision 0008 (G-05)
recorded this as a deferred interaction:

> **IMP-003 / H-04 interaction (deferred, must be honored):** the credit is
> measured with `time.monotonic()` (in `service_await`/`service_sleep`) while
> the ceiling's `started_ts` and `caps_exceeded` use `time.time()`
> (`caps.py`, `loop.py`, `runtime.py`). This is the pre-existing mixed time
> base that IMP-003/H-04 will unify. When H-04 lands, the parked credit and
> `started_ts` must move to the same monotonic base together — the
> subtraction is only meaningful within one clock.

A wall-clock jump (NTP correction, VM resume, manual set) moves `time.time()`
without moving `time.monotonic()`. Under the mixed base this could do two
opposite bad things to the same guarantee (R3, ceiling caps):

- **Mask a cap:** a backward jump makes `time.time() - started_ts` hugely
  negative — a genuinely over-budget agent stops tripping `wall_clock` for
  the rest of its run.
- **Kill a healthy agent:** a forward jump makes the elapsed term explode —
  an agent with hours of legitimate budget left is killed instantly.

Both failure modes attack the exact guarantee the vision says the runtime
must own (INFO-053: ceiling caps "bind regardless of any budget edit the
agent makes" — and, a fortiori, regardless of what the wall clock does).

A full inventory of every clock call in `src/` (22 sites, archived evidence
`h04_time_inventory.md`) found exactly **two** wall-clock timestamp sites
participating in duration math — `loop.py:278` (origin) and `caps.py:192`
(the comparison's "now") — and confirmed the parked-credit side of the same
chain is already monotonic. Every other timeout mechanism in the tree
(`repl.py` step timeout via `worker.join(timeout)`, the LLM driver's SDK
timeouts and `thread.join(self.timeout)`, `runtime.py` join timeouts, all
`time.sleep` polling) is a bare duration with no clock base, and the two
remaining duration comparisons (`state.py:325` snapshot throttle,
`benchmark/run.py:165,171` latency) are already monotonic.

## Decision

**All duration comparisons use `time.monotonic()`.** The wall-clock ceiling
moves to the monotonic base, origin and comparison together:

- `src/dhc/agent/loop.py` — `started_ts = time.monotonic()` (pump start).
- `src/dhc/agent/caps.py` — the ceiling comparison becomes
  `time.monotonic() - started_ts - max(parked_seconds, 0.0) > timeout_seconds`.

This discharges 0008's recorded interaction exactly as specified: the parked
credit (already monotonic) and `started_ts` now share one base, so the
subtraction `elapsed - credit` is meaningful within a single clock. The
credit itself needed no change — it was already on the right base; the
defect was the wall-clock side.

**Informational timestamps stay wall-clock.** `agent.created_ts`
(`agent.py:135`), `agent.settled_ts` (`runtime.py:567`), checkpoint
`updated_at`, `events.jsonl`/`trace.jsonl` timestamps, and the
`Event`/`Message`/`Turn` model defaults are records for humans and
post-hoc inspection; none is ever read back into a comparison (verified by
consumer grep). Converting them to monotonic would destroy their wall-clock
readability with zero correctness benefit. The name `started_ts` is kept
(it is still a timestamp — just a monotonic one).

## Rationale

1. **The ceiling is a duration guarantee, not a calendar one.**
   `timeout_seconds` means "this agent may not run for more than N seconds
   of real time." Real elapsed time is what `time.monotonic()` measures;
   `time.time()` additionally encodes the operator's clock discipline
   (NTP, timezone-free but jump-prone). A guarantee the vision places in
   the runtime's hands must not depend on the host's clock discipline.
2. **The mixed base was not merely untidy — it was exploitable by
   accident.** The 0008 arithmetic `time.time() - started_ts -
   parked_seconds` subtracts a monotonic duration from a wall-clock
   elapsed. A backward wall jump of more than the parked credit makes the
   effective elapsed negative (cap masked); a forward jump adds phantom
   seconds (healthy agent killed). The jump test pins both directions.
3. **Minimal and complete.** The inventory shows exactly two sites carry
   the defect; both move in one commit. No other duration math exists in
   the tree, so "all duration comparisons on one monotonic base" is
   grep-verifiable: after this change, no `time.time()` remains in any
   duration comparison (the only remaining `time.time()` calls in `src/`
   are the informational records listed above).
4. **Records stay honest.** Keeping `created_ts`/`settled_ts`/event
   timestamps on wall clock preserves their meaning ("when did this happen,
   in human time") and their existing test assertions, and keeps the
   diff minimal.

## Changes made

- `src/dhc/agent/loop.py` — `started_ts = time.monotonic()` (one line; the
  comment now names the monotonic base and the 0008 interaction).
- `src/dhc/agent/caps.py` — the wall-clock branch of `cap_hit` compares
  against `time.monotonic()`; docstrings updated to name the monotonic
  base.
- `tests/agent/test_composition_wave1.py` — the three `started_ts`
  injections flip from `time.time() - 10.0` to `time.monotonic() - 10.0`.
  This is the decision-required pinning update, not a weakening: the test
  still pins the identical arithmetic (10 s elapsed / 6 s credit / 5 s
  ceiling), now on the base the predicate actually reads. The parent's
  constraint "composition test stays green unmodified" is honored in
  substance — the pinned semantics (clamp+credit composition) are
  unchanged; only the injected clock base moves with the predicate (a
  `time.time()`-based injection would make the elapsed term hugely
  negative against a monotonic `started_ts` and the ceiling would
  silently stop tripping — the test would pass vacuously).
- `tests/agent/test_event_fanout.py` — six `started_ts` injections flip
  from `time.time()` to `time.monotonic()` (same reason: they feed the
  same predicate; a wall-clock value against a monotonic base never
  trips).
- `tests/agent/test_g05_parked_time.py` — three `started_ts` injections
  flip from `time.time() - 10.0` to `time.monotonic() - 10.0` (same
  reason).
- `tests/agent/test_h04_monotonic_timebase.py` — new: the wall-clock-jump
  tests (below).

## Verification

Full suite green (see the run log in the commit). New tests, all in
`tests/agent/test_h04_monotonic_timebase.py`:

1. `test_h04_wall_clock_jump_forward_does_not_trip` — a busy agent under a
   5 s ceiling survives a simulated +3600 s wall-clock jump mid-run; no
   `wall_clock` crash event; the agent completes.
2. `test_h04_wall_clock_jump_backward_does_not_mask` — a busy agent under
   a 0.2 s ceiling is still killed by `wall_clock` despite a simulated
   -3600 s wall-clock jump mid-run; the crash event names cap and limit.
3. `test_h04_parked_credit_and_started_ts_same_base` — pins the 0008
   interaction directly at the predicate seam: with `started_ts` taken
   from `time.monotonic()`, a wall-clock jump of ±3600 s changes nothing
   about the trip decision (the credit and the origin are on the same
   base; the jump is invisible to the comparison).
4. `test_h04_no_wall_clock_in_duration_math` — grep-able invariant: no
   `time.time()` remains in `caps.py`/`loop.py` duration math (asserts the
   source of both modules contains no `time.time()` in the ceiling chain;
   guards against regression to a mixed base).

The clamp+credit composition test (`test_composition_wave1.py`) stays green
with the base flip (criterion 4).

## Alternatives Considered

- **Keep wall clock everywhere (convert the credit to wall).** Rejected:
   the credit is a duration measured across a park; wall-clock jumps
   during the park would corrupt the credit itself (a backward jump could
   make a 5 s park measure as -3600 s, un-crediting time and killing a
   healthy parked agent — the exact anti-pattern 0008 exists to prevent).
   Monotonic is the correct base for measuring durations.
- **A dedicated clock seam (injectable `clock=` callable).** Rejected for
   now: no test or caller needs to inject a clock (the jump tests
   monkeypatch `time.time` at the module seam, which is enough), and a
   new seam is a new surface to maintain. The two-line change achieves
   the guarantee without it.
- **Convert informational timestamps to monotonic too.** Rejected: see
   Rationale 4 — records must stay wall-clock readable; none is read
   back into a comparison.

## Consequences

- The wall-clock ceiling is now immune to wall-clock jumps in both
  directions: a jump can neither trip nor mask a cap.
- `started_ts` is a monotonic timestamp. Anything that persisted it
  across process restarts would be meaningless — nothing does (it is a
  per-run local in `pump_loop`; verified by consumer grep).
- The three test files that inject `started_ts` values now inject
  monotonic values; future tests that force the ceiling must use
  `time.monotonic()` (pinned by test 4's source invariant).
- 0008's recorded IMP-003 interaction is discharged: the parked credit
  and `started_ts` are on the same monotonic base, and the composition
  test pins that they compose.
