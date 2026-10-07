---
id: 0004
type: decision
title: "IMP-001 D4 — Deterministic default fabrications; driver becomes decide"
date: 2026-10-07
status: accepted
---

# D4 — Deterministic default fabrications; driver becomes `decide`

## Context

The `MockDriver` suite, the operator/root door, and `examples/value_demo.py`
all depend on the current driver contract (`__call__(agent) -> str | None`)
and the current turn loop. Moving the loop into the workspace (D1) risks
breaking every existing test unless the default workspace behavior replicates
today's behavior exactly. The scoping question is how backward compatibility
is provided: a default fabrication kit, no default at all, or a parallel
legacy path.

## Decision

Every workspace is born with a **fabrication kit** whose defaults replicate
today's behavior exactly:

- default `__runner` (the resumable generator that reproduces the current
  turn loop),
- `decide(context)` — wraps the current LLM/Mock brain,
- `run_block`,
- `context` (guardrails / inbox / outbox / budgets / digests),
- channel handles (`messenger`, `room`, `escalate`, `ask`),
- checkpoint / rollback / compact helpers,
- a visible caps view.

`driver.__call__` becomes the default `decide` fabrication; its bookkeeping
(`_turns`, `_calls`) moves into workspace state. `ensure_fabrication`
re-seeds any fabrication the agent broke or deleted (e.g. `__runner = 42` →
re-seed the default; event emitted).

**Backward compatibility is "the default fabrication," not a second execution
path.** There is exactly one loop: the default `__runner` is what the current
loop becomes.

## Rationale

The `MockDriver` suite and operator/root door keep their contracts and
determinism on the default loop; backward compatibility is the default
fabrication, not a second execution path — two loops to maintain is the
failure mode this decision avoids. `ensure_fabrication` makes the default loop
None-safe: a broken or deleted fabrication is re-seeded on demand, so a
degrading agent cannot take itself (or the mesh) down by breaking its own
workspace.

## Alternatives Considered

- **No default** (agents must bootstrap a loop) — breaks all existing tests
  and the operator/root door. Rejected.
- **A separate legacy path in parallel** — two loops to maintain, and the
  legacy path becomes a permanent second execution path. Rejected.

## Consequences

- `driver.py`: `__call__` becomes the default `decide(context)` fabrication;
  prompt assembly becomes a fabrication; rot observation moves into the
  default loop's observe step.
- `wiring.py` / `agent.py`: inject the fabrication kit into the namespace;
  expose `run_block`, `context`, channels as workspace citizens;
  `ensure_fabrication`; keep the in-code surface (INFO-041) stable on the
  default loop.
- The `MockDriver` integration suite and `examples/value_demo.py` must pass
  **unmodified** on the default loop — this is the backward-compat gate for
  the whole injection.
- Determinism: custom loops break scripted-driver tests unless policies
  default to the fabrications; fixtures must swap `__runner`/`decide` as
  cells.