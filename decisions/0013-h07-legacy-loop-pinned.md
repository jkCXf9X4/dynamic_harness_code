---
id: 0013
type: decision
title: "H-07 — The legacy loop path is required by the bare in-memory core: pinned, not retired"
date: 2026-10-09
status: accepted
---

# H-07 — The legacy turn loop stays (pinned), because the bare core has no pump

## Context

`src/dhc/agent/loop.py` carries two loop implementations behind a dispatch:

- `pump_loop` (`loop.py:241`) — the pumped path: drives the agent's
  `__runner` generator one yield-window at a time under the four hard
  gates (settlement, containment, ceiling caps, cancellation) plus the
  caps watchdog and the rot tripwire. The main path for every wired
  runtime (`build_runtime`, `src/dhc/wiring.py:402-409`).
- `legacy_loop` (`loop.py:144`) — the exact old `_worker_loop` body:
  decide → execute → settle, turn-based, no caps watchdog, no rot gate.
- The dispatch: `pump_agent` (`loop.py:130-141`) calls
  `runtime._supports_pump()`; `supports_pump` (`loop.py:93`) is true when
  `runtime.repl_engine` is set **or** `runtime.engine` has `advance`.

The roadmap (H-07, gap-analysis §C Wave 3; §D open question 2) asks
whether the legacy path is "dead weight from the pre-pump era" that can
be removed, or a live surface that must stay.

## Investigation (the evidence)

**Which engines still require the legacy path?**

The tree has three engines:

| Engine | Pump primitives (`advance`/`install`/`inject`/`kill`/`suspend`/`resume`/`globals_for`/`has_workspace`) | Path |
|---|---|---|
| `ReplEngine` (`src/dhc/agent/repl.py:55`) | all | pump |
| `_ReplEngineAdapter` (`src/dhc/wiring.py:188`) | wraps ReplEngine; `runtime.repl_engine` is set alongside it (`wiring.py:409`) | pump |
| `_MemoryEngine` (`src/dhc/agent/runtime.py:75`) | **none** — a turn-based `exec()` engine with only `execute` | **legacy** |

`TracingEngine` (`src/dhc/data/trace.py:114`) is a test-surface wrapper
used directly against an engine (`tests/agent/test_checkpoint_trace.py`),
never installed as a `Runtime` engine — it is not a loop consumer.

**Who runs on the legacy path?** (grep: `Runtime(` without `build_runtime`)

1. **The production `dhc` CLI** — `src/dhc/cli.py:130` constructs
   `Runtime(settings=settings)` (bare: `_MemoryEngine`, no
   `repl_engine`), starts it, and drives every operator request through
   it. Every agent the CLI spawns settles through `legacy_loop`.
2. **The core contract tests** — `make_runtime()` in
   `tests/agent/test_runtime.py` (a bare `Runtime()`) with ~27 spawn
   call sites, and `tests/ui/test_operator.py` (`Operator.run` spawns).
   `test_runtime.py:707` records the split explicitly: "The legacy
   in-memory path is covered by the tests above (make_runtime)."
   The remaining bare-`Runtime()` sites (`test_tools.py:158`,
   `test_events_tool.py`, `test_state.py`'s `NoBusRuntime`) touch
   `_build_namespace`/`_emit` directly and never spawn — they are not
   loop consumers.

So the legacy path is **live on a real surface**, not dead code.

## Decision

**Pin the legacy path.** `legacy_loop`, `supports_pump`, and the
`pump_agent` dispatch stay, documented and pinned by
`tests/agent/test_h07_legacy_loop.py`. The legacy path is the loop of
the *bare in-memory core* — the engine-agnostic `Runtime(engine, bus,
store)` of decision 0007's module separation — not a duplicate of the
pump.

## Rationale

1. **An engine genuinely needs it.** The pump is not a loop over
   `execute`; it is a loop over the ReplEngine's resumable-runner
   primitives (`install`/`advance`/`inject`/`kill`/`suspend`/`resume`/
   `globals_for`/`has_workspace`). `_MemoryEngine` has none of them, by
   design: it is the minimal turn-based core. The parent's retirement
   condition — "if retiring turns out to require more than a decision +
   removal (e.g. engines genuinely need it), pin it" — is met.
2. **Retiring means one of two larger changes, both worse.**
   - *Migrate every bare-`Runtime` user to the wired runtime:* the CLI
     would move from a zero-footprint in-memory core to the full wired
     stack (workspace dirs, artifact store, fabrication kit) — a
     behavior change to a production entry point — and ~30 core
     contract tests would need the `_pumped_runtime(tmp_path)` fixture
     shape. That is a migration project, not a removal.
   - *Give `_MemoryEngine` the pump primitives:* that is re-implementing
     `ReplEngine` (snapshot/rollback, per-step timeout, suspend/resume)
     a second time — strictly more dual-maintenance surface than the
     ~100-line turn loop it would delete.
3. **The two loops are not two implementations of one thing.** The pump
   is the agent-owned-loop path (fabrication kit, `__runner`, yield
   vocabulary, caps, rot). The legacy loop is the *engine-agnostic
   core's* turn loop — the seam that keeps `runtime.py` free of any
   REPL dependency (0007). Deleting it does not remove a duplicate; it
   removes the core's only loop.
4. **The cost of pinning is bounded and now explicit.** Before this
   decision the split was an undocumented "known defect" (gap-analysis
   §B small defect 5). After it, the requirement, its consumers, and
   its limitation (below) are recorded once in a decision record and
   enforced by a test that fails if the dispatch or the path silently
   changes.

## Changes made

- `decisions/0013-h07-legacy-loop-pinned.md` — this record.
- `tests/agent/test_h07_legacy_loop.py` — new pinning tests (below).
  No production code changes: pinning is the decision.

## Verification

Full suite green (see the run log in the commit). New tests, all in
`tests/agent/test_h07_legacy_loop.py`:

1. `test_h07_bare_runtime_falls_back_to_legacy` — a bare `Runtime()`
   (the CLI's shape, `cli.py:130`) reports `supports_pump() is False`:
   the dispatch condition is pinned.
2. `test_h07_wired_runtime_uses_pump` — the wired runtime
   (`build_runtime`) reports `supports_pump() is True`: the main path is
   the pump, and the dispatch never sends a wired agent to legacy.
3. `test_h07_legacy_path_drives_bare_runtime_agents` — an agent spawned
   on a bare `Runtime()` completes, and its event stream carries the
   legacy path's `turn_started` payload shape (`{"code": ...}`, the
   turn loop's) rather than the pump's (`{"step": ...}`): the path is
   exercised end-to-end, not dead code.
4. `test_h07_memory_engine_lacks_pump_primitives` — the mechanical
   reason, pinned: `_MemoryEngine` has none of the eight primitives the
   pump requires.
5. `test_h07_repl_engine_provides_pump_primitives` — the contrast:
   `ReplEngine` provides all eight, so the pump's contract is real, not
   vacuous.

## Alternatives Considered

- **Retire: remove `legacy_loop` + `supports_pump` dispatch, migrate the
  consumers.** Rejected on Rationale 2 — it is a CLI behavior change
  plus a ~30-test migration, exactly the scope explosion the retirement
  option was conditioned on not needing.
- **Retire: implement the pump primitives on `_MemoryEngine`.** Rejected
  on Rationale 2 — a second `ReplEngine` to maintain is more duplicated
  surface than the loop it deletes.
- **Retire: make `Runtime()` default to `ReplEngine`.** Rejected: it
  couples the engine-agnostic core to the REPL (against 0007's module
  separation) and silently changes the CLI's footprint and behavior.

## Consequences

- The legacy path stays as the bare core's loop; the dispatch
  (`supports_pump`) remains the single seam that routes an agent to it.
- **Documented limitation:** the legacy path enforces no ceiling caps
  and no rot tripwire between turns (those are pump gates). The bare
  in-memory core is the minimal engine-agnostic runtime; the wired
  runtime — the path the vision's agent-owned loop describes — enforces
  all four hard gates. This is pre-existing behavior, now recorded.
- If the CLI ever migrates to `build_runtime` (a product decision, not a
  hygiene one), the legacy consumers shrink to the core contract tests
  and this decision should be revisited.
