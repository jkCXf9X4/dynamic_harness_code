---
id: INFO-067
type: info
title: Test strategy
summary: What the test suite verifies and how — mirrored unit tests, the framework-tooling import boundary guard, integration through build_runtime, and top-level acceptance
date: 2026-10-10
status: current
---

# Test strategy

The suite verifies the runtime at three levels: mirrored unit suites, an architectural boundary guard, and top-level end-to-end tests. Integration and acceptance levels run the deterministic `MockDriver`; determinism itself is owned by `INFO-056`.

## Unit suites mirror the package

- Each `tests/` subdirectory tests the matching `src/dhc/` package: `framework`, `tooling`, `ui`, `data`, `llm`, `benchmark`.
- `tests/framework` tests the control loop; `tests/tooling` the composed agent world; `tests/ui` the operator side.
- Cross-cutting tests stay at the `tests/` top level.
- Suite layout, filing rule, baseline: `tests/README.md`.

## The boundary guard

- `tests/framework/test_core_tooling_boundary.py` imports every module under `dhc.framework`, then scans module attributes for leaked values.
- **Import direction**:
  - No `dhc.framework` module holds a value defined in `dhc.tooling`, `dhc.ui`, or `dhc.llm`.
  - The composition root `dhc.wiring` is the only meeting point.
- **Tool homes**:
  - No `*.py` file in `dhc/framework/` has `tool` in its name.
  - `framework_tools.py`, `channel_tools.py`, `artifact_tools.py` live in `dhc.tooling`.
- **Pump, not loop**:
  - `dhc/framework/pump.py` exists; `loop.py` does not.
  - The default agent `fabrication.py` lives in `dhc.tooling`.
  - A pumpable runtime with no composed kit settles failed, reason `no fabrication composed`.
  - `build_runtime` hands in the kit factory from `dhc.tooling.fabrication`.
- **Operator files**: `state.py` and `checkpoint.py` live in `dhc.ui`, never in the framework.
- **Store unawareness**: `Runtime.__init__` and `Agent.__init__` take no `artifact_store` parameter.
- **Message primitive**: `send` binds in the core namespace; channel tools `room`, `messenger`, `escalate`, `ask_operator`, `post`, `channel_read` stay out.

## Integration through build_runtime

- `tests/test_integration.py` drives the real modules wired by `build_runtime(mock=True)`: `ReplEngine`, `EventBus` plus `BoundaryEventLog`, `CompletionDispatcher`, `ArtifactStore`, channels.
- **Covered**:
  - Full session: root spawns three children, two complete, one fails contained, root aggregates and settles.
  - Boundary log records `spawned`, `settled`, `published` with causal ids.
  - Double settlement raises `ChannelError` — settlement is at-most-once.
  - Disclosure tiers `headline`, `summary`, `report` round-trip through the real store.
  - `driver_from_settings` picks `MockDriver` without an API key; `mock=True` forces it with one.
  - A messenger message crosses the boundary log as kind `messaged`.

## Acceptance on top

- `tests/test_imp001_acceptance.py` exercises the D1..D5 gates end to end on the fully-wired pumped runtime (`INFO-068`).
- Every containment scenario there asserts sibling liveness — the mesh stays alive.

## Owns
- What the suite verifies and the verification strategy: mirrored unit suites, the boundary guard, integration through `build_runtime`, top-level acceptance.

## Excludes
- Commands to run the suite — `INFO-056`.
- Suite layout, filing rule, baseline — `tests/README.md`.
- The D1..D5 gate content — `INFO-068`.
- The benchmark harness — `INFO-069`.
