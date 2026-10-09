---
id: 0017
type: decision
title: "Arch — The framework owns the pump, not the loop: the default agent is composition"
date: 2026-10-09
status: accepted
---

# Arch — The framework owns the pump, not the loop

## Context

After `0016` made the framework/composition split the folder hierarchy,
one conflation remained, visible in two places:

- the framework's machinery module was named `loop.py` — it reads as
  "the framework owns the agent's loop", the exact ambiguity the split
  was supposed to kill; and
- the agent loop's *content* — the default `__runner__` (the
  `decide → run_block → observe → settle, yield "step"` semantics) and
  the whole fabrication kit (decide, run_block, context,
  checkpoint/rollback/compact, caps view, build_prompt) — lived in
  `llm/fabrication.py`, imported *by* the framework
  (`loop.py`, `runtime.py`). That was the named-but-unmoved debt of
  `0016`: a framework → llm edge that inverted the layering, with the
  default agent parked in provider plumbing.

The product vision is unambiguous about the classification
(`INFO-053`, the control split):

- under **agent control**: "The main loop. How the agent works —
  orchestration and its cadence — is workspace code the agent views,
  edits, and replaces; the default loop ships as a fabrication the
  agent starts from." Also the decision policy, including prompt
  assembly.
- under **runtime control**: settlement, containment, ceiling caps,
  cancellation, event discipline, enforcement timing, completion
  dispatch, and *fabrication integrity* — a broken or deleted default
  is re-seeded by the runtime.

So the runtime's job is to guarantee a loop EXISTS and to enforce
around it; the loop's content is agent-side. `0016`'s own classifier
("semantics the core interprets is framework") draws the same line:
the core interprets the runner *contract* (compile / install /
re-install / re-seed, the yield vocabulary); it does not interpret the
loop's cadence.

Four facts found in review made the move cheaper than `0016` feared:
`runtime.py`'s fabrication import was dead (imported, never used); a
bare `Runtime()` is never pumpable (`0013`/h07 — no `repl_engine`, so
the legacy loop), and every pumpable runtime in the repo (32 test call
sites, the CLI, production) is built by the composition root;
`integrity.py` is already kit-driven (it duck-calls
`kit["ensure_fabrication"]()`); and the pump's only remaining kit
couplings are the birth call and two `DEFAULT_RUNNER_SOURCE`
comparisons, both derivable from the kit itself.

## Decision

1. **`framework/loop.py` is renamed `framework/pump.py`.** The module
   is the pump: the machinery that drives agent-authored loops one
   yield-window per step under the four hard gates, the runner
   install/re-install seams, the yield-servicing park/resume helpers,
   and the legacy turn loop for non-REPL engines. The framework drives
   loops; it does not author them.
2. **The default agent moves to `tooling/fabrication.py`** (from
   `llm/fabrication.py`). The fabrication kit is what a workspace is
   born with — the composed side's default implementation of the
   runner contract. `llm/` becomes a pure provider leaf (llm, driver,
   prompts).
3. **The seam: `Runtime(kit_factory=...)`.** The composition root
   (`wiring.build_runtime`) hands `tooling.fabrication.fabrication_kit`
   to the runtime; the pump calls the factory at workspace birth. A
   pumpable runtime without a factory cannot birth an agent and
   settles failed with a clear reason (containment, not a crash).
   The pump's `DEFAULT_RUNNER_SOURCE` comparisons now derive from the
   kit (`kit["__runner"]`); `install_runner` raises if a kit provides
   no runner source.
4. **The dependency graph is now fully one-way downward:**
   framework → {data, errors} ONLY; llm → {data, errors} (leaf);
   tooling → {framework, llm, data, errors}; ui → {framework, tooling};
   wiring → all. The framework imports neither tooling, nor ui, nor
   llm.
5. **The guard test extends** (`tests/framework/test_core_tooling_boundary.py`):
   no `dhc.framework` module may import `dhc.llm` (in addition to
   tooling/ui); `pump.py` must exist and `loop.py` must not; the
   fabrication kit must live in `dhc.tooling`; a pumpable runtime
   without `kit_factory` settles failed with "no fabrication
   composed"; `build_runtime` hands in the tooling kit factory.

## Consequences

- Zero behavior change: the same kit, the same pump, the same events —
  the kit is handed in by the composition root instead of reached for
  by the framework. The MockDriver suite, acceptance fixture, and
  `value_demo` pass unmodified (the D4 backward-compat gate).
- The D4 invariant holds with sharper wording: there is exactly one
  default loop, and it is a *composed* fabrication — "backward
  compatibility is the default fabrication" now also names where it
  lives. The engine precedent (`INFO-053`) still holds: the REPL engine
  is removable and framework, because the core operates it
  (install/advance/inject/kill); the kit is what the substrate gets
  *filled with* — the agent's birth content — and is composition.
- Tooling gains an edge to `llm` (`fabrication` imports
  `driver_from_settings` / `default_build_prompt`): the default agent
  needs a brain. No cycle — `llm` is a leaf.
- Tests mirror the moves: `tests/llm/test_fabrication.py` →
  `tests/tooling/`; import paths updated elsewhere.
- The 0016 layout docstrings/READMEs are updated (framework owns "the
  pump and the runner contract, not the loop's content").

## Rejected alternatives

- **Move the kit into `framework/` as the agent's birthright** (like
  the engine): keeps a framework → llm import forever (the kit's decide
  wraps `driver_from_settings`; `build_prompt` is prompt assembly),
  and puts agent-swappable policies inside the "small, stable set of
  guarantees". The vision lists the default loop under agent control.
- **Keep the kit in `llm/`**: the default agent is not provider
  plumbing; the placement was IMP-001 geography, not classification.
- **No default at all** (agents bootstrap their own loop): rejected by
  D4 and still wrong — it breaks the determinism of the mock path.
- **A second, minimal framework-carried kit as the bare-runtime
  default**: two kits is D4's named failure mode. A bare `Runtime()`
  is legacy-path anyway (never pumpable), so no second kit is needed.
