---
id: 0016
type: decision
title: "Arch — The repo layout IS the boundary: dhc.framework (zero tools) vs dhc.tooling (the agent's composed world) vs dhc.ui (the operator's side)"
date: 2026-10-09
status: accepted
---

# Arch — The repo layout IS the boundary

## Context

Decisions 0014 (the artifact store) and 0015 (direct messaging) drew the
framework-vs-composed-tooling boundary in code, but the folder hierarchy
still hid it:

- the framework lived in a package misleadingly named `dhc.agent` — a
  browser reads "agent" as agent-side, the opposite of the truth;
- the framework's own tools layer (`dhc.agent.tools`) sat INSIDE the
  framework package — the one place the split says no composed tool
  belongs;
- `dhc.agent.state` (the operator's review files) and
  `dhc.agent.checkpoint` (the operator's resumability, 0012) — the
  placement debt 0014 named and deliberately did not move — were
  non-framework leaves parked in the framework package;
- `dhc.tooling` held the channels and the store, but the framework-surface
  tools were elsewhere, so "what an agent gets in its REPL" had no single
  home.

The user directive: the separation between the framework and the
agent-tooling/inside-REPL artifacts must be concrete in the folder
hierarchy — very clear when browsing the repo.

## Decision

1. **`dhc.agent` is renamed `dhc.framework`.** The package is the control
   loop and its guarantees — runtime, loop, agent surface, REPL, event
   stream, context triggers, rot policy, caps, integrity — plus the
   directed-message primitive (`send`, 0015). The name now says what it
   is.
2. **The framework package ships ZERO tools.** `dhc.agent.tools` moves to
   `dhc.tooling.framework_tools` (the `list_tools`/`events` tools that
   wrap framework surfaces, installed by `register_default_tools`).
   Everything installed into an agent REPL namespace beyond the core
   actions now has one home, `dhc.tooling`: `framework_tools`,
   `channels` + `channel_tools`, `artifact_store` + `artifact_tools`,
   `adapters`.
3. **The 0014 placement debt is resolved by moving the files to their
   owning sides:** `dhc.agent.state` (StateWriter — the operator's review
   files) → `dhc.ui.state`; `dhc.agent.checkpoint` (the operator's
   resumability store, 0012) → `dhc.ui.checkpoint`. Both are the
   operator's files; `ui/` is the operator's side (door, terminal, review
   files, resumability).
4. **`wiring.py` is the single meeting point** — the only module that
   imports both `dhc.framework` and `dhc.tooling` (and `dhc.ui`). The
   dependency directions: framework → (`data`, `errors`) only; tooling →
   framework (one-way); ui → framework, tooling; wiring → all.
5. **Tests mirror the layout**: `tests/agent` → `tests/framework`; the
   framework-tools tests → `tests/tooling/test_framework_tools.py` +
   `test_events_tool.py`; state tests → `tests/ui/`; checkpoint tests →
   `tests/ui/`.
6. **The guard test extends and becomes a layout test** (decision 0016):
   no `dhc.framework` module may import `dhc.tooling` or `dhc.ui`; the
   framework package must contain no `*tools*` module; the tool homes
   must exist in `dhc.tooling`; state/checkpoint must live in `dhc.ui`.

## Consequences

- Broad but mechanical import churn (32 `git mv` renames, no behavior
  changes): every `dhc.agent.X` import became `dhc.framework.X` (or the
  module's new home); the golden prompts and all tests pass unchanged in
  content.
- `dhc.agent` is gone — no alias, a clean cut (pre-1.0, the repo is the
  only consumer). Browsing the tree now answers the classification
  question at a glance: framework = what runs agents; tooling = what
  agents get in their REPLs; ui = the operator's side; wiring = the only
  meeting point.
- Known follow-up debt, named not moved here: the fabrication kit
  (`llm/fabrication.py`) straddles the framework (the pump seeds the
  default `__runner__` from it and `integrity` re-seeds it —
  `framework/loop.py` and `framework/runtime.py` import it) and the
  composed world (wiring installs the kit into workspaces). It also
  imports `llm.driver`. Moving it means splitting bootstrap-necessary
  parts from composed parts — real surgery, out of scope. The
  framework → llm import direction therefore remains, guarded only
  against `tooling` and `ui`.
  **Resolved by `0017`:** the framework owns the pump and the runner
  contract (renamed `framework/pump.py`); the default agent — the
  whole fabrication kit — moved to `dhc.tooling.fabrication` and is
  handed in via `Runtime(kit_factory=...)` at the composition root;
  the framework now imports only `data` + `errors` (the guard also
  forbids `llm`).
- `tests/framework` is the slow directory (the runtime suites); the
  framework/tools/ui/tooling split of tests makes the suite's geography
  readable too.

## Rejected alternatives

- **Keep the `dhc.agent` name** (clarity loses: the most important
  browsing signal — "this package is the framework" — stays inverted).
- **A `dhc.agent` alias re-exporting `dhc.framework`** (two homes for one
  package defeats the point of a browseable split).
- **A third package for the composed side** (e.g. `agentkit`):
  `tooling` is the established name from 0014/0015 and the user's own
  vocabulary — "channels should be a strict tooling".
- **Moving `llm/fabrication.py` in this pass**: see Consequences — the
  kit is framework-bootstrap-necessary (the pump cannot run without
  seeding a runner), so it cannot simply move to `tooling/` without
  inverting a dependency the guard forbids.
- **Moving `state.py`/`checkpoint.py` into `tooling/`**: both are the
  *operator's* files (review, resumability — 0012 says so explicitly);
  their home is the operator's side, not the agent's composed world.
