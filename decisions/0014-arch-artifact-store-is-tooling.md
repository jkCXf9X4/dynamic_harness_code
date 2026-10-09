---
id: 0014
type: decision
title: "Arch — The artifact store is operator tooling, not framework: the seam stays, the storage moves to dhc.tooling"
date: 2026-10-09
status: accepted
---

# Arch — The artifact store is operator tooling, not framework

## Context

Artifacts (INFO-006) are the durable medium through which agents communicate
findings to each other and to the operator **without polluting each other's
context**: agents hand off by content-addressed id and pull
progressive-disclosure tiers (headline → summary → report) on demand. That
role — context-preserving communication — is a property of the *seam* (ids
in, tiers out, one event emitted), not of any particular storage
implementation.

Before this decision the line was drawn differently in the code:

- the on-disk `ArtifactStore` + `BoundaryEventLog` lived in `src/dhc/data/`
  and were re-exported from the package top level as framework API;
- the framework core carried store seams: `Runtime.__init__(artifact_store=…)`
  with an in-memory `_MemoryStore` default, `Agent(artifact_store=…)` with an
  `Agent.publish()` method, and a `store` slot on the tools-layer
  `ToolContext`;
- `decisions/0012` classified the on-disk store as "operator-facing runtime
  state … the same layer as the artifact store, the event stream, and the
  caps".

The core demonstrably did not *need* the store. It ran without one
(`_MemoryStore` default); `Agent.publish()` had exactly one caller in the
repository (a unit test); and agent-authored code published through the
*namespace tool* (`dhc.agent.tools._publish`), which already emitted the
framework's `artifact_published` event on the bus. Publication was thus
already a framework-native concept (an event kind); only the *persistence*
was framework-adjacent.

## Decision

**The artifact store is operator tooling, not a framework concern.** The
framework core (`src/dhc/agent/`) knows artifacts in exactly two ways:

1. as **opaque ids** carried on `Result`/`Completion` (agents pass ids; the
   core never resolves them); and
2. as **event vocabulary**: `EventKind.artifact_published` on the runtime's
   event bus, persisted through the already duck-typed bus sink.

Concretely:

- `ArtifactStore`, `BoundaryEventLog`, and `BOUNDARY_EVENT_KINDS` move from
  `src/dhc/data/` to a new `src/dhc/tooling/` package; the `StoreAdapter`
  (`put` → `publish(h, s, r)`) and `BoundarySink` (events → boundary log)
  adapters move from `wiring.py` into `dhc.tooling.adapters` and are
  promoted to public tooling names.
- The four store-backed namespace tools (`publish`, `read_artifact`,
  `archive`, `list_artifacts`) move from `dhc.agent.tools` to
  `dhc.tooling.artifact_tools`, installed by
  `dhc.tooling.register_artifact_tools` with the same namespace-wrapping
  mechanics as `register_default_tools`. `list_tools` now reports only the
  tools actually installed on a runtime (a `Runtime` without the store
  tooling does not advertise `publish`).
- The framework loses all store seams: `Runtime.__init__` no longer takes
  `artifact_store`, `_MemoryStore` is deleted, `Agent.publish()` is deleted,
  and `ToolContext` no longer has a `store` field.
- `wiring.build_runtime` remains the **only** place the store is
  instantiated; it attaches the adapter as `runtime.artifact_store` (raw
  store as `runtime.artifact_store_real`) post-construction — the same
  wiring-level decoration already used for `runtime.operator`,
  `runtime.boundary_log`, `runtime.bus`, etc. The core class neither
  defines nor reads these attributes.
- The package-level re-exports of `ArtifactStore` / `BoundaryEventLog` /
  `BOUNDARY_EVENT_KINDS` are removed from `dhc/__init__.py`; the canonical
  import path is `dhc.tooling`.

Dependency direction is locked by `tests/agent/test_core_tooling_boundary.py`:
no module under `dhc.agent` may import `dhc.tooling`, and `Runtime`/`Agent`
constructors must not expose a store parameter.

## Consequences

- **Wired stacks: zero behavior change.** The agent namespace is identical
  (the store tools are installed by the composition root either way), the
  `artifact_published` events are identical, and the on-disk layout under
  `settings.artifact_root` is unchanged.
- **Bare stacks lose publication.** A zero-footprint `Runtime` no longer
  carries an in-memory store or an `Agent.publish()` method; publishing is a
  composed tool. This is intended: the bare core is now unambiguously
  store-free (the only repository caller of `Agent.publish()` was a unit
  test, which was replaced by a negative assertion).
- **0012's classification is superseded for the store.** The
  "operator-facing runtime state" layer keeps the event stream and caps; the
  on-disk store is reclassified as operator *tooling* composed at the
  composition root. The control-split argument (the operator owns persisted
  evidence; the agent does not) is unchanged — it now simply lives on the
  tooling side of the seam.
- **0013's CLI-migration item is reframed** as a tooling choice: the CLI
  (chat TUI) adopting the artifact store is an operator decision, not a
  framework migration.
- **Known wart, not widened here:** `Settings.artifact_root` is operator
  config consumed by tooling, and `state._default_root` derives the run root
  from its *parent* path. Both remain path-level only; no store object
  crosses the line.
- **Where the refined line falls:** the channel tools (`room`, `messenger`,
  `escalate`, `ask_operator`, `post`, `channel_read`) remain in
  `dhc.agent.tools` deliberately — they relay communication on the runtime's
  own event bus and persist nothing, so they are framework-side composition
  even though the core runs without them. Removability is not the classifier
  (the core also runs without a real engine); what classifies a concern is
  whether the core carries its data opaquely to operator-side persistence
  (tooling) or the concern relays communication and execution semantics the
  runtime owns (framework-side). **Superseded by `0015`:** the line was
  drawn one level finer — the *relay primitive* (`Runtime.send`, a
  receiver-addressed message event) is framework, and the channel *policies*
  (rooms, escalation, operator questions, the inbox view) moved to
  `dhc.tooling`, so the agent keeps full control of its communication.
  The classifier above stands, sharpened: the core *interprets* the
  message event (routes, caps, persists it), which is what makes the
  primitive framework rather than carried tooling.
- **Adjacent placement debt, named not moved:** two more operator-side
  persistence modules still live inside the framework package —
  `dhc.agent.state` (writes `agent_tree.json` / `stats.json` / `events.jsonl`
  for manual operator review) and `dhc.agent.checkpoint` (the operator's
  resumability mechanism, dormant in production per 0012). Both are
  self-contained leaves — nothing in the core imports them, and their
  dependencies are one-way framework-ward — so they violate no enforced
  boundary, but by the classifier above they are tooling-class concerns and
  candidates for the same move as a follow-up. The operator side also spans
  two packages: `ui/` (the interaction surface, including state *renderers*
  such as the `/artifacts` viewer) and `tooling/` (state *infrastructure*);
  the classifier classifies concerns, the guard test enforces the core seam.
  **Resolved by `0016`:** `state` → `dhc.ui.state` and `checkpoint` →
  `dhc.ui.checkpoint` (the operator's side — both are the operator's
  files), the framework package is renamed `dhc.framework` with zero
  tools inside it, and the tools layer itself moved to
  `dhc.tooling.framework_tools`.

## Rejected alternatives

- **Typed `ArtifactStoreProtocol` in the core** — would have kept the
  framework aware of the store's shape; the requirement was awareness-free,
  and the event seam already carries the semantics the core needs.
- **Publish as a framework event payload** (agent emits
  `artifact_published` carrying the full report; tooling persists from the
  bus) — would put full report bodies into the event stream (footprint, and
  persist-before-execute sink pressure), and the existing tool path already
  does the store-then-emit-id dance the boundary log expects.
- **Move the store out of the `dhc` package** (separate package/repo) —
  rejected as churn; the store is an operator concern *of this runtime*, and
  an in-package `tooling/` subpackage with a one-way dependency is
  sufficient.
