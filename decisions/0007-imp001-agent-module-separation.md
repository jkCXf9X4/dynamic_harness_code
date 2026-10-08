---
id: 0007
type: decision
title: "IMP-001 — Agent module separation: loop, caps, integrity, and context triggers extracted from runtime.py"
date: 2026-10-08
status: accepted
---

# Agent module separation — loop, caps, integrity, and context triggers out of `runtime.py`

## Context

The scoping brief (run `261008_105638_6a18`) found three concerns entangled in
one 1058-line god object (`src/dhc/agent/runtime.py`) sharing one lock and one
mutable frame:

- **(a) The agent loop** — `_pump_loop` (236 lines) inlined the caps watchdog,
  completion drain, fabrication re-seed, runner install, and yield servicing;
  `_settle`, `_emit`, and `_build_namespace` sat beside it.
- **(b) Context triggers** — no prune/compress/summarize module existed; three
  scattered mechanisms (a *dormant* `ContextRotDetector`, the trim-50 digest,
  and the caps tripwires) could not be evolved or tested until separable.
- **(c) Tool calls** — `tools.py` (already its own module) stayed put.

Eight coupling points resisted separation (the brief's §2): the destructive
`_MemoryBus.drain` race, the Runtime god object, the fabrication kit closing
over runtime privates, reflective state reads, the kit-dict double role, three
wall-clock bases, stringly-typed event kinds, and two parallel loop bodies.

This record covers the **pure extraction** that follows: behavior unchanged,
public API unchanged, no new dependencies, no reformatting. It is a separate,
reviewable diff from the upcoming drain-race fix.

## Decision

**Option A — package split by concern** (the scoping brief's §5 recommendation).
New modules under `src/dhc/agent/`: `loop.py` (the loop concern), `caps.py`
(the ceiling-caps watchdog predicate), `integrity.py` (fabrication
ensure/re-seed), and `context.py` (the context-trigger seam). `runtime.py`
re-exports the moved callables so the public API is unchanged; `tools.py` is
untouched.

The split is deliberate and bounded: it captures the seams that already exist
(a pure caps predicate, a duck-typed rot detector needing one wiring line, and
`ctx["observe"]` around the only real pruning) at moderate risk, without the
larger blast radius of Option C's protocol/registry rewrite.

## Changes made

- **Loop extraction** — `runtime.py` 1058 → 595 lines. New `agent/loop.py`
  (562 lines) owns `pump_agent`, `pump_loop`, `legacy_loop`, the yield
  vocabulary (`Await`/`Poll`/`Sleep`), and `install_runner`/`service_await`/
  `service_sleep`/`step_timeout`/`supports_pump`.
- **Caps** — new `agent/caps.py` (113 lines): the watchdog predicate plus the
  five ceiling-cap defaults.
- **Integrity** — new `agent/integrity.py` (38 lines): the best-effort
  `ensure_fabrication` re-seed calls (IMP-001 Step 5, D4).
- **Context wiring** — new `agent/context.py` (62 lines): `DIGEST_KEEP = 50`,
  `trim_digest`, and `make_observe` (the digest observe/trim — the only real
  pruning). `fabrication.py`'s `make_observe` becomes a thin delegate to it;
  `driver.py`'s `driver_from_settings` gains a `rot_detector` parameter;
  `wiring.py`'s `build_runtime` now constructs a `ContextRotDetector`
  (INFO-021, observe-only) so the driver's per-block observation actually
  collects.
- **Re-exports** — the eight moved loop callables are re-exported from
  `runtime.py` (verified 8/8 `is`-identical to `dhc.agent.loop`).
- **Test-side** — two fixes in `tests/test_context.py` (299 lines, four
  classes: `TestTrimDigest`, `TestObserveDigest`, `TestMakeObserve`,
  `TestDetectorWiring`); the prior run's two `TestDetectorWiring` failures are
  resolved.

## Verification

Independently verified (do not re-run): full suite **416 passed / 0 failed**
(371.04s), up from the 394-test pre-refactor baseline; re-exports **8/8**;
Phase-2 hard gates **(d)–(g) all PASS** (settlement at-most-once, crash
containment, ceiling caps, cancellation grace). Evidence:
`.dynamic-harness/verify/spot/EVIDENCE.md` (archived `5fcbc3da3038`).

## Hazards disposition

- **`_MemoryBus` drain race** — `drain` clears the topic and four consumers
  race on `events:<id>` (caps watchdog, `Runtime.events`,
  `LLMDriver._recent_context`, the StateWriter poll thread); the first drainer
  starves the rest. **Implemented** (commit `2605b44`): every bus exposes a
  non-destructive `peek()` alongside the destructive `drain()`
  (`_MemoryBus`, `EventStream`, `_WiredBus`), and each consumer keeps its own
  cursor over the non-destructive stream — `Runtime.events` a per-agent
  cursor (consume-once semantics preserved), the caps watchdog a per-step
  delta (gate-(f) behavior unchanged), the StateWriter poll thread its own
  watermark (each event forwarded exactly once). The `completions:<id>`
  topics stay destructive (INFO-046 at-most-once). Proven by
  `tests/agent/test_event_fanout.py`.
- **Stringly-typed event kinds** — `state.py` matches event kinds by string
  literals instead of the `EventKind` enum. **Open** — IMP-002.
- **Wall-clock bases** — `time.time` and `time.monotonic` are mixed across the
  caps timeout, the step start, and the sleep deadline. **Open** — IMP-003.
- **Inert token fields** — `AgentNode`'s token/cost fields are never
  populated. **Open** — IMP-004.

## Alternatives Considered

- **Option B (single-module split)** — extract only the caps watchdog,
  fabrication ensure, yield servicing, and context observe; `runtime.py` keeps
  the dicts and lock. Smallest blast radius, but leaves the god object and the
  sharpest hazard (the drain race) in place. Rejected.
- **Option C (protocol + registry seams)** — formalize
  Driver/CapMonitor/ContextTrigger protocols + a ToolRegistry and a
  non-destructive bus peek/fan-out. Largest blast radius (wiring root,
  fabrication kit, all tool callables, bus semantics); changed drain semantics
  can starve or duplicate events if wrong. Rejected for now; its registry work
  can follow incrementally once the modules exist.

## Consequences

- `runtime.py` is now an orchestrator plus a re-export facade; the loop, caps,
  integrity, and context concerns each live in their own module behind an
  explicit seam.
- The context-trigger seam is explicit and testable (`tests/test_context.py`);
  the dormant rot detector is wired at the composition root (observe-only).
- The public API (`dhc.cli:main`, the Runtime contract, `build_runtime`,
  `register_default_tools`) is unchanged; D2's four hard gates stay
  pump-owned; the fabrication kit remains the only backward-compat path (D4).
- The `_MemoryBus` drain race is fixed (commit `2605b44`, see the hazards
  disposition above); the three open hazards are tracked as IMP-002/003/004.
