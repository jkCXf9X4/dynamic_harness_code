---
id: 0008
type: decision
title: "G-05 — Parked-time semantics for the wall-clock ceiling: parked time is credited"
date: 2026-10-08
status: accepted
---

# Parked-time semantics — the wall-clock ceiling excludes time spent parked

## Context

INFO-053 (`breakdown/01-product/the-control-split-agent-vs-runtime.md`) puts
waiting under agent control — "**Waiting.** How the agent waits — await,
poll, sleep; waiting on others consumes no agent budget" — and ceiling caps
under runtime control — "**Ceiling caps.** Wall-clock, step count, workspace
size, child count, and message rate bind regardless of any budget edit the
agent makes."

The implementation freed the *step* budget (D3: `step_count` does not
advance while parked, `src/dhc/agent/loop.py`) but not the *wall clock*:
`started_ts` was set once at pump start (`loop.py`) and
`caps_exceeded` compared raw elapsed time against `timeout_seconds`
(`src/dhc/agent/caps.py`). A parent that spawned a child and parked on
`yield Await(child)` was killed at resume for the **child's** slowness —
the wall clock ran while the parent was doing exactly what the vision
recommends (cheap cooperation, INFO-052: "waiting on others does not consume
an agent's own capacity to act").

The ambiguity (roadmap G-05, gap-analysis §B row A8 caveat, §D open
question 1): does "agent budget" in the Waiting bullet include the
wall-clock ceiling, or only the step budget?

## Decision

**Parked time is excluded from the wall-clock ceiling.** The pump
accumulates the seconds each agent spends parked on `yield Await(child)`
and `yield Sleep(t)` and passes the cumulative credit to the caps
watchdog; the wall-clock check compares
`time.time() - started_ts - parked_seconds > timeout_seconds`.

The wall-clock ceiling remains a runtime guarantee that binds for all
*non-parked* wall time. It is not weakened: a busy agent (steps that never
park) still trips it, a runaway step is still bounded by the step timeout,
and an agent that parks forever is still terminated by cancellation.

## Rationale

1. **The vision's spirit is unambiguous even where its letter is not.**
   INFO-052 frames the goal as "from expensive supervision to cheap
   cooperation": waiting on others must not cost the waiter. Under
   pre-0008 semantics the parent paid with its life for the child's
   slowness — the single most delegation-shaped pattern the vision exists
   to enable. Reading "budget" as step-budget-only would make the Waiting
   bullet true while its motivation ("cheap cooperation") is false.
2. **Exclusion weakens nothing that the ceiling actually guarantees.**
   The wall-clock watchdog runs *between* steps (R6, enforcement timing),
   so it already provides zero containment *during* a park — a parent
   parked on a never-settling child was already beyond the wall clock's
   reach under the old semantics. What contains a parked-forever agent is
   cancellation (R4), which is unchanged and now pinned by test. Runaway
   *steps* are contained by the per-step timeout and the iterations cap,
   both untouched.
3. **The alternative (bind while parked) has no compensating strength.**
   Option (b) documents the current behavior as intended: "the wall clock
   is a mesh-survival guarantee, not an agent budget." But as (2) shows,
   the mesh-survival story for parked agents was never carried by the wall
   clock — it is carried by cancellation. Option (b) would preserve a
   guarantee that does not exist while keeping the anti-pattern penalty.
4. **The credit is bounded and runtime-owned.** The accumulator lives in
   pump code the agent cannot edit (R3: caps read runtime state only); the
   credit is clamped at zero below (`max(parked_seconds, 0.0)`) and can
   never exceed elapsed time because it is measured by the pump itself
   around `engine.suspend`/`engine.resume`.

## Changes made

- `src/dhc/agent/caps.py` — `caps_exceeded` gains an optional
  `parked_seconds: float = 0.0` keyword; the wall-clock branch subtracts
  it. No other cap branch is touched (G-01 owns the iterations branch).
- `src/dhc/agent/loop.py` — the pump accumulates `parked_seconds`;
  `service_await`/`service_sleep` now return the parked duration
  (previously `bool`); the Await/Sleep branches add it to the accumulator
  and then check the stop flag themselves (the cancelled path still
  settles cancelled — the parked duration is simply not credited on a path
  that terminates).
- `src/dhc/agent/runtime.py` — `_caps_watchdog` forwards
  `parked_seconds`; `_service_await`/`_service_sleep` wrappers re-type to
  `float` (re-export seam preserved: the pump still calls
  `runtime._service_*`, so monkeypatching the Runtime methods keeps
  working).
- `tests/agent/test_g05_parked_time.py` — 5 new tests (below).

## Verification

Full suite **429 passed / 0 failed** (with `PYTHONPATH=src`; the
subprocess-spawning `test_value_demo_runs_unmodified` needs it in this
environment — pre-existing, unrelated to this change). Baseline before the
change: 424 passed. New tests, all in
`tests/agent/test_g05_parked_time.py`:

1. `test_g05_parked_await_excluded_from_wall_clock` — a parent parked on
   `yield Await(slow_child)` for 1.5 s against a 1.0 s ceiling, child alive
   throughout, completes normally; no `wall_clock` crash event.
2. `test_g05_busy_agent_still_trips_wall_clock` — an agent that keeps
   stepping without parking trips `wall_clock` (0.05 s ceiling) with the
   crash event naming cap and limit.
3. `test_g05_runaway_step_still_trips_step_timeout` — `while True: pass`
   is still bounded by the step timeout (rollback + timeout settlement).
4. `test_g05_cancel_terminates_parked_agent` — cancellation terminates a
   parked agent: settles cancelled, runner killed (`advance` →
   `abandoned`), child released, mesh alive.
5. `test_g05_wall_clock_credit_arithmetic` — the credit arithmetic pinned
   directly at the watchdog seam: 10 s elapsed / 5 s ceiling trips; +6 s
   credit does not; +4 s credit still does.

## Alternatives Considered

- **(b) Wall clock binds while parked (status quo, documented).** Simplest
  — no code, only a pinning test and a rationale paragraph. Rejected on
  Rationale 1–3: it keeps punishing the delegation pattern and defends a
  guarantee (mesh survival while parked) the wall clock never actually
  provided.
- **Credit only Await-parks, not Sleep-parks** ("waiting on *others*").
  Textually defensible, but Sleep is also waiting, the distinction is
  invisible to the agent, and it doubles the accounting surface for no
  containment gain. Rejected for simplicity.
- **A separate parked-time ceiling** (e.g. wall clock binds, plus a
  max-parked-seconds cap). Adds a sixth cap and a new config surface for a
  case cancellation already contains. Rejected.

## Consequences

- A parent awaiting a slow child is no longer killed for the child's
  slowness; the child's own busy time still binds its own ceiling.
- An agent that parks forever is contained by cancellation only. This is
  now the documented containment path for parked agents (pinned by test
  4). Operators cancelling a mesh get parked agents killed at the next
  10 ms poll (`service_await`/`service_sleep` poll the stop flag).
- **IMP-003 / H-04 interaction (deferred, must be honored):** the credit
  is measured with `time.monotonic()` (in `service_await`/`service_sleep`)
  while the ceiling's `started_ts` and `caps_exceeded` use `time.time()`
  (`caps.py`, `loop.py`, `runtime.py`). This is the pre-existing mixed
  time base that IMP-003/H-04 will unify. When H-04 lands, the parked
  credit and `started_ts` must move to the same monotonic base together —
  the subtraction is only meaningful within one clock. Until then the
  credit is a duration (a difference), which is far less exposed to
  wall-clock jumps than an absolute timestamp, but the mixed base remains
  a known defect owned by H-04, not fixed here.
- The `service_await`/`service_sleep` return-type change (bool → float)
  is internal to the pump seam; no test or caller outside
  `loop.py`/`runtime.py` used the old boolean (verified: no other call
  sites).
