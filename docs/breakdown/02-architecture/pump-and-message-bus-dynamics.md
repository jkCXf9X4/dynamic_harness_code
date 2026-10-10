---
id: INFO-062
type: info
title: Pump and message bus dynamics
summary: How the pump and the message bus behave over time — demand-driven stepping, the between-actions interleave of one pump iteration, park servicing, and where the pump and the bus meet
date: 2026-10-10
status: current
---

# Pump and message bus dynamics

- The pump and the bus share one rhythm: each pump iteration interleaves bus consumption, gate checks, one agent step.
- This leaf records that rhythm; the static contracts it animates are cited, not restated.

## Stepping

- Stepping is demand-driven, not rate-driven: the pump advances the runner one yield-window whenever the agent is not parked — no scheduler, no quantum, no tick (`INFO-037`).
- Each agent's pump runs on its own worker unit (`INFO-038`).
- A bare in-memory runtime takes the legacy loop instead — no caps watchdog, no rot gate (`INFO-055`).

## One pump iteration

Between agent actions, in this order:

- Stop-flag check first: a cancelled agent settles before any new step (`INFO-037`).
- Completion drain: settled-child callbacks run in completion order (`INFO-047`).
- Ceiling caps check (`INFO-037`), then rot tripwire check (`INFO-061`).
- Fabrication re-seed when the runner is broken or deleted (`INFO-037`).
- `turn_started` emitted to the events topic with the step number.
- One `advance` under the step timeout; the yield outcome classifies the next state.
- Yield outcomes: `Await` parks on a handle, `Sleep` parks until a deadline, `Poll` returns without parking (status injected as `yield_result`).
- Terminal outcomes: `finished`, `timeout`, `error` settle the agent at most once each (`INFO-046`).

## Park servicing

- Parked runner is suspended, not spinning (`INFO-037`).
- **Await** parks at 10 ms poll granularity.
  - Each pass drains the parent's completions, so awaiting never stalls the queue (`INFO-047`).
- **Sleep** parks until its deadline, polling at 10 ms or the remaining time, whichever is smaller.
- Parked parent advances no steps and consumes no wall-clock budget (`INFO-053`, `INFO-060`).
- A parked-forever agent is contained by cancellation, not the wall clock (`INFO-053`).

## Step bound

- Every step runs under a step timeout, default 120 s: the engine runs the runner's next chunk in a daemon worker and joins with the timeout (`INFO-060`).
- On timeout the workspace rolls back to the per-step snapshot; the runner is abandoned, never resumed (`INFO-037`).

## Bus flows

- Two topic families per agent: `events:<id>` for telemetry and directed messages, `completions:<id>` for settled-child completions (`INFO-047`, `INFO-048`).
- Publish path: the event sinks once before routing, then fans out to the target agent's stream and global subscribers (`INFO-048`, `INFO-049`).
  - A sink failure aborts the emit: persistence is the durability guarantee.
  - Subscriber callback errors are contained, never reach the publisher.
- `events:<id>` is non-destructive: each consumer keeps its own cursor over `peek()` (`INFO-048`).
- `completions:<id>` is destructive, FIFO, at-most-once (`INFO-046`).
- Directed messages and channel posts land on the recipient's `events:<id>` topic (`INFO-054`).

## Where pump and bus meet

- The pump is the sole consumer of the completion topic on the pumped path — always between actions, never concurrent with agent code (`INFO-047`).
- The pump is the sole producer of per-step `turn_*` telemetry.
- The message-rate cap is a bus delta: pending messages counted per step over the non-destructive peek (`INFO-037`, `INFO-048`).
- The rot tripwire reads the driver's score between steps (`INFO-061`).
- The runner's observe step drains fresh events into the digest, trimmed to a sliding window (`INFO-055`).

## Owns

- The pump cycle's dynamic behavior: demand-driven stepping, the between-actions interleave order, park servicing and its timing, the step bound.
- The message flow's dynamic behavior: publish path and fan-out, consumption timing, and the coupling points where the pump produces or consumes bus traffic.

## Excludes

- The contracts this leaf animates: pump and gates (`INFO-037`), settlement (`INFO-046`), dispatch (`INFO-047`), stream discipline (`INFO-048`), boundary log (`INFO-049`).
- Supporting contracts: worker placement (`INFO-038`), parked-time semantics (`INFO-053`), directed-message delivery (`INFO-054`), composition (`INFO-058`), time base (`INFO-060`), guardrail placement (`INFO-061`).
- Module-level layout of the pump — `INFO-055`.
