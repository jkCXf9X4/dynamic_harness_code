---
id: 0012
type: decision
title: "H-06 — Two checkpoint mechanisms: the split is intended (agent workspace vs operator on-disk)"
date: 2026-10-09
status: accepted
---

# H-06 — the two checkpoint mechanisms are a deliberate control split, not a vision violation

## Context

The vision's A3 surface (`breakdown/01-product/the-control-split-agent-vs-runtime.md`)
says the agent's *context and history* are "full accumulated state as ordinary
data" the agent can read. Roadmap Wave 3 item H-06 (and open question 4) flagged
an apparent tension: two checkpoint mechanisms coexist, and the agent cannot
read its own on-disk checkpoint.

- **(1) Workspace checkpoints** — `state["checkpoints"]` in the fabrication kit
  (`src/dhc/llm/fabrication.py`, the `checkpoint`/`rollback`/`compact` citizens).
  Agent-owned, in-memory, part of the agent's own namespace. The agent reads and
  writes these freely; they are ordinary data in its context.
- **(2) On-disk `CheckpointStore`** — `src/dhc/agent/checkpoint.py`
  (`AgentCheckpoint`/`CheckpointStore`/`CheckpointDriver`), surfaced to the
  operator via `/resume` in the terminal UI (`src/dhc/ui/terminal.py`).

The question H-06 poses: is the agent's inability to read its own on-disk
checkpoint a violation of A3, or a deliberate operator/agent split?

## Finding that settles it

The on-disk `CheckpointStore` is **dormant in production**. It is never
instantiated anywhere in `src/`: `wiring.py`'s `build_runtime` never sets
`runtime.checkpoint_store`, so the terminal's `/resume` handler
(`getattr(self.runtime, "checkpoint_store", None)`) always resolves to `None`
and reports "no checkpoint". The store is exercised only in isolation by
`tests/agent/test_checkpoint_trace.py`. It is a *peripheral wrapper* — a
reference-project pattern (mirroring `core/checkpoint.py`) kept as a tested,
operator-facing resumability seam, not a live mechanism.

By contrast, the workspace `state["checkpoints"]` is the **live, agent-owned**
mechanism: it is a fabrication citizen, re-seeded by `ensure_fabrication`, and
read/written by the agent as ordinary namespace data.

So the two mechanisms are not two competing implementations of one thing. They
are two different layers of the control split:

- **Workspace checkpoints = the agent's.** They are the agent's own
  accumulated state, readable and writable by the agent — exactly what A3
  promises. A3 is satisfied: the agent's context and history *are* ordinary
  data it can read.
- **On-disk `CheckpointStore` = the operator's.** It is the operator's
  resumability mechanism (a durable, out-of-process snapshot the operator can
  inspect and resume from the terminal). It is deliberately *not* in the
  agent's context: it is the runtime's side of the control split, the same
  layer as the artifact store, the event stream, and the caps — operator-facing
  state the agent does not own.

## Decision

**Document the split as intended.** Do not unify. The on-disk store stays
operator-only; the workspace checkpoints stay the agent's. The split is the
control split made concrete, and it is consistent with A3 (the agent's own
context/history are ordinary data; the operator's resumability store is the
runtime's side).

Concretely:

- Add a docstring to the workspace `checkpoint` citizen
  (`src/dhc/llm/fabrication.py`) stating it is the agent's own in-workspace
  mechanism, distinct from the operator's on-disk `CheckpointStore`.
- Add a comment to the terminal's `/resume` handler
  (`src/dhc/ui/terminal.py`) stating it reads the operator's on-disk store,
  which is separate from the agent's workspace checkpoints.
- Add a test that pins the split: the on-disk store is never instantiated in
  production wiring (operator-only), and the agent's workspace checkpoint
  mechanism does not touch the on-disk store (the two are independent).

## Why not unify

Unifying (exposing the on-disk store to the agent as a tool) would be the wrong
move for three reasons:

1. **It is dormant.** There is no production writer, so an agent-facing tool
   would expose an always-empty store — no value, only surface area.
2. **Different scope.** The on-disk `AgentCheckpoint` captures a coarse
   snapshot (agent_id, requirement, acceptance, status, turn_counter, notes);
   the workspace checkpoints capture the agent's full namespace state. They are
   not the same data, so "unifying" would mean either a lossy projection or a
   redesign of the on-disk model — neither justified while the store is dormant.
3. **It would blur the control split.** The whole point of the split is that
   the agent owns its context and the operator owns the runtime's durable
   state. Giving the agent a read handle on the operator's store inverts that
   boundary for no benefit.

If the on-disk store is ever wired into production (a future decision), the
question of agent-readability can be revisited then — with a real writer and a
real reason. Until then, the split is the correct, minimal, vision-consistent
state.

## Verification

Pinned by `tests/agent/test_checkpoint_split.py`:

- the on-disk `CheckpointStore` is never constructed in `src/dhc/wiring.py`
  (operator-only, dormant in production);
- the terminal's `/resume` reads the operator's `runtime.checkpoint_store`
  (the operator's side), not the agent's workspace checkpoints;
- the agent's workspace `checkpoint` citizen writes only to
  `state["checkpoints"]` and never to the on-disk store (the two mechanisms are
  independent).

Full suite green (473 baseline + new).

## Consequences

- A3 is satisfied as written: the agent's context and history are ordinary data
  it can read (the workspace checkpoints). The on-disk store is the operator's
  resumability mechanism, correctly outside the agent's context.
- The two mechanisms are now explicitly documented at both sites, so the split
  is discoverable and intentional rather than an accident.
- No behavior change; no new dependencies; the dormant on-disk store is left
  as-is (a tested peripheral wrapper, ready to be wired if a future decision
  wants operator resumability).
