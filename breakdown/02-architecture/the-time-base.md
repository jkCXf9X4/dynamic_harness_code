---
id: INFO-060
type: info
title: The time base
summary: Runtime clock discipline - every duration comparison runs on time.monotonic(); informational timestamps stay wall-clock
date: 2026-10-09
status: current
---

# The time base

- Every duration comparison in the runtime uses `time.monotonic()`.
- Informational timestamps stay wall-clock.
- Wall-clock jump (NTP correction, VM resume, manual set) moves `time.time()` without moving `time.monotonic()`.
  - So no guarantee may depend on the host's clock discipline.

## Duration comparisons (monotonic)

- **Wall-clock ceiling**:
  - `started_ts = time.monotonic()` at pump start (`framework/pump.py`).
  - Compared as `time.monotonic() - started_ts - max(parked_seconds, 0.0) > timeout_seconds` in `framework/caps.py`.
- **Parked-time credit**:
  - Measured around `engine.suspend`/`engine.resume` in `service_await`/`service_sleep`.
  - Same base as `started_ts`, so the subtraction is meaningful within one clock.
- **Snapshot throttle** (`ui/state.py`): already monotonic.
- **Benchmark latency** (`benchmark/run.py`): already monotonic.
- **Other timeout mechanisms in the tree**:
  - Bare durations with no clock base.
  - `repl.py` step timeout via `worker.join(timeout)`.
  - The LLM driver's SDK timeouts.
  - `thread.join(self.timeout)`.
  - Runtime join timeouts.
  - All `time.sleep` polling.

## Informational timestamps (wall-clock)

- **Human-facing records**:
  - `agent.created_ts`
  - `agent.settled_ts`
  - Checkpoint `updated_at`
  - `events.jsonl`/`trace.jsonl` timestamps
  - `Event`/`Message`/`Turn` model defaults
  - For humans and post-hoc inspection.
  - None read back into a comparison.
- `started_ts` keeps its name: still a timestamp, a monotonic one.
- Per-run local in `pump_loop`.
- Nothing persists it across process restarts.

## Owns
- Clock discipline: which comparisons are monotonic, which timestamps are wall-clock, why the split exists.

## Excludes
- Parked-time semantics the credit implements: `INFO-053`.
- Decision that set the base: `AD-007`.
