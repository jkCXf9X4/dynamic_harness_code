<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->

# Decision Stream

Flat, dated history of every committed design choice. Current state lives
in the layer leaves named by each record's `state:` field.

Records live in the cold-storage archive; extract one with `pb archive read <ID>`.

## By Layer

### Product

- **PD-001** — Parked-time semantics for the wall-clock ceiling: parked time is credited · accepted · 2026-10-08 · `PD-001`
  Time an agent spends parked on Await or Sleep is excluded from the wall-clock ceiling; the ceiling binds all non-parked wall time and parked-forever agents are contained by cancellation.
- **PD-002** — Two checkpoint mechanisms: the split is intended (agent workspace vs operator on-disk) · accepted · 2026-10-09 · `PD-002`
  The two checkpoint mechanisms are a deliberate control split: workspace checkpoints are the agent's; the on-disk CheckpointStore is the operator's, dormant in production.

### Architecture

- **AD-001** — Kernel made real · accepted · 2026-10-07 · `AD-001`
  The turn engine is a workspace-owned, agent-authored resumable generator that the runtime pumps one yield-window at a time.
- **AD-002** — Four hard gates are pump behavior · accepted · 2026-10-07 · `AD-002`
  The agent sees and edits its whole workspace, bounded only by four hard gates that are pump behavior, not variables.
- **AD-003** — Op vocabulary split by cost · accepted · 2026-10-07 · `AD-003`
  The op vocabulary splits by cost: bounded sync ops are direct calls; indefinite or off-thread ops are yield requests serviced by the pump.
- **AD-004** — Default ships as fabrication kit · accepted · 2026-10-07 · `AD-004`
  Every workspace is born with a fabrication kit whose defaults replicate today's loop exactly; backward compatibility is the default fabrication, not a second path.
- **AD-005** — Guardrails three-part placement · accepted · 2026-10-07 · `AD-005`
  Guardrails decompose into three parts: normative (context-in), operational (pump-evaluated tripwires), and reactions (executed in the parent's REPL).
- **AD-006** — Event stream consumed in-loop (partial reversal of INFO-048) · accepted · 2026-10-07 · `AD-006`
  Event-stream consumption moves into the loop while the discipline (FIFO, at-most-once, persist-before-execute) stays runtime-owned.
- **AD-007** — Single monotonic time base for all duration comparisons (H-04) · accepted · 2026-10-09 · `AD-007`
  All duration comparisons use time.monotonic(); informational timestamps stay wall-clock, so wall-clock jumps can neither trip nor mask a cap.
- **AD-008** — Arch — The artifact store is operator tooling, not framework: the seam stays, the storage moves to dhc.tooling · accepted · 2026-10-09 · `AD-008`
  The artifact store is operator tooling — the framework core knows artifacts only as opaque ids and the artifact_published event; storage moves to dhc.tooling.
- **AD-009** — Arch — Direct agent communication is framework; channels are tooling over the primitive · accepted · 2026-10-09 · `AD-009`
  Direct agent-to-agent messaging is a framework primitive (Runtime.send, receiver-addressed message_sent); every channel is strict operator tooling composed over it.
- **AD-010** — Arch — The repo layout IS the boundary: dhc.framework (zero tools) vs dhc.tooling (the agent's composed world) vs dhc.ui (the operator's side) · accepted · 2026-10-09 · `AD-010`
  The repo layout is the boundary — dhc.framework ships zero tools, dhc.tooling holds everything installed into agent REPLs, dhc.ui is the operator's side, wiring.py is the single meeting point.
- **AD-011** — Arch — The framework owns the pump, not the loop: the default agent is composition · accepted · 2026-10-09 · `AD-011`
  The framework owns the pump and the runner contract, not the loop's content — the default agent (the fabrication kit) is composed tooling handed in via Runtime(kit_factory=...).

### Implementation

- **IMD-001** — Agent module separation: loop, caps, integrity, and context triggers extracted from runtime.py · accepted · 2026-10-08 · `IMD-001`
  The 1058-line runtime.py god object is split by concern into loop, caps, integrity, and context modules behind a re-export facade, with behavior and the public API unchanged.
- **IMD-002** — Enum-driven event-kind mapping in the state snapshot · accepted · 2026-10-09 · `IMD-002`
  The state snapshot matches EventKind members against an explicit terminal table, failing loudly at import and test time instead of dropping events.
- **IMD-003** — Token/cost accumulation at the driver seam · accepted · 2026-10-08 · `IMD-003`
  Usage accumulates at the driver seam with one write and one read, and the mock path reports zeros.
- **IMD-004** — H-07 — The legacy loop path is required by the bare in-memory core: pinned, not retired · accepted · 2026-10-09 · `IMD-004`
  The legacy turn loop stays pinned as the loop of the bare in-memory core, because _MemoryEngine has no pump primitives and the CLI plus core contract tests run on it.
- **TC-001** — IMP-001 — Adopted task contract (Phase 1 governance gate) · accepted · 2026-10-07 · `TC-001`
  Adopts the 6-step task contract as the Phase-1 governance gate for IMP-001, fixing the execution foundation, the hard gates, and the per-step acceptance criteria

### Operation

- **OD-001** — Deprecation ruling — pre-studies and analysis artifacts are transient, retired by deletion · accepted · 2026-10-09 · `OD-001`
  Pre-studies and analysis artifacts are transient working documents, retired by deletion once their decisions land; future deprecations of STATE files follow the deprecated-files protocol (retire into the archive deprecated/ namespace).
