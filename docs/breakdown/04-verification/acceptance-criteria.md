---
id: INFO-068
type: info
title: Acceptance criteria
summary: The end-to-end criteria the kernel contract must satisfy — the D1 to D5 gates exercised by the acceptance suite
date: 2026-10-10
status: current
---

# Acceptance criteria

The D1..D5 gates the kernel contract must satisfy end to end, plus the runaway-containment scenario. One test per gate in `tests/test_imp001_acceptance.py`, each a parent/child flow on the fully-wired pumped runtime — `ReplEngine` plus fabrication kit. Every containment scenario ends with a sibling spawned after still completing.

## D1 — resumable generator

- The agent replaces `__runner` with a custom generator source string.
- The pump compiles it through the custom-runner seam and drives it one yield-window at a time.
- The custom steps execute in order; each yield is classified — `turn_completed` carries the yield's step number.
- The agent completes through the pump, not the legacy path.

## D2 — the four hard gates

- **Settlement at-most-once**:
  - Exactly one child completion lands in the parent stream.
  - A second settle of the same agent raises `ChannelError`.
- **Crash containment**:
  - A runner that raises mid-run costs one agent, not the mesh.
  - The crasher settles failed with the exception text in the reason.
- **Outer ceiling cap**:
  - `max_iterations=1` force-stops the agent with reason `cap exceeded`.
  - A crash event carries the cap name `iterations` and the limit.
- **Cancellation grace**:
  - Cancellation lands between steps: kill, rollback, settle cancelled.
  - The runner is never resumed — `advance` returns `abandoned`.
  - The workspace rolls back; no partial mutation survives.

## D3 — Await without step-budget burn

- `yield Await(child)` parks the parent without advancing its step count.
- A fast sibling completes during the park; its completion reaches the parent stream while the parent is still parked.
- Once the awaited child settles, the parent resumes and completes.
- Blocking `await_` still works on the default loop.

## D4 — deterministic default fabrications

- A plain spawn on the default loop completes with the fabrication intact: `__runner` equals `DEFAULT_RUNNER_SOURCE`, `decide` callable, `context` bound to the agent.
- `ensure_fabrication` re-seeds a broken fabrication (`__runner = 42`) between steps, emits a crash event naming the reseeded names, and the agent continues on the default loop.
- `examples/value_demo.py` passing unmodified is checked by `tests/tooling/test_fabrication.py::test_value_demo_runs_unmodified`.

## D5 — guardrail placement

- **Normative**: parent-imposed guardrails arrive as visible context-in at delegation; the child sees them in its workspace and internalizes them into `context.guardrails`.
- **Operational**: a `max_iterations` tripwire is pump-evaluated between steps and fires though the agent's code never checks it.
- **Reactions**: a reaction ships as a completion-style event on the parent stream; the `on_done` callback runs in the parent's REPL.
  - The child never executes its own termination — it settles failed without cancelling itself.

## Runaway containment

- A `while True: pass` loop is bounded by the step timeout.
- The runaway settles `timeout` within 5 s; a timeout event is emitted.
- The workspace rolls back — the partial mutation is gone.

## Owns
- The D1..D5 end-to-end acceptance criteria and the runaway-containment scenario.

## Excludes
- The improvement that introduced this suite — `IMP-001`.
- The kernel contract itself — `INFO-037`.
- How to run the suite — `INFO-056`.
- The suite's strategy shape — `INFO-067`.
