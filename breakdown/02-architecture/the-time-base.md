---
id: INFO-060
type: info
title: The time base
summary: The runtime's clock discipline — every duration comparison runs on time.monotonic(); informational timestamps stay wall-clock
date: 2026-10-09
status: current
---

# The time base

All duration comparisons in the runtime use `time.monotonic()`. Informational
timestamps stay wall-clock. A wall-clock jump (NTP correction, VM resume,
manual set) moves `time.time()` without moving `time.monotonic()`, so no
guarantee may depend on the host's clock discipline.

## Duration comparisons (monotonic)

- The wall-clock ceiling: `started_ts = time.monotonic()` at pump start
  (`framework/pump.py`), compared as
  `time.monotonic() - started_ts - max(parked_seconds, 0.0) > timeout_seconds`
  in `framework/caps.py`.
- The parked-time credit measured around `engine.suspend`/`engine.resume` in
  `service_await`/`service_sleep` — same base as `started_ts`, so the
  subtraction is meaningful within one clock.
- The snapshot throttle (`ui/state.py`) and benchmark latency
  (`benchmark/run.py`) — already monotonic.
- Every other timeout mechanism in the tree (`repl.py` step timeout via
  `worker.join(timeout)`, the LLM driver's SDK timeouts and
  `thread.join(self.timeout)`, runtime join timeouts, all `time.sleep`
  polling) is a bare duration with no clock base.

## Informational timestamps (wall-clock)

- `agent.created_ts`, `agent.settled_ts`, checkpoint `updated_at`,
  `events.jsonl`/`trace.jsonl` timestamps, and the `Event`/`Message`/`Turn`
  model defaults — records for humans and post-hoc inspection; none is read
  back into a comparison.
- `started_ts` keeps its name: still a timestamp, just a monotonic one. It is
  a per-run local in `pump_loop`; nothing persists it across process restarts.

## Owns
- The clock discipline: which comparisons are monotonic, which timestamps are
  wall-clock, and why the split exists.

## Excludes
- The parked-time semantics the credit implements — `INFO-053`.
- The decision that set the base — `AD-007`.
