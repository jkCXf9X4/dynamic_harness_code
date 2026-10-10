<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->

# Decision Log

Chronological history, newest first. Generated from the flat decision
stream.

| Date | ID | Decision | Layers | Status | Record |
|---|---|---|---|---|---|
| 2026-10-09 | PD-002 | Two checkpoint mechanisms: the split is intended (agent workspace vs operator on-disk) | product | accepted | `PD-002` |
| 2026-10-09 | OD-001 | Deprecation ruling — pre-studies and analysis artifacts are transient, retired by deletion | operation | accepted | `OD-001` |
| 2026-10-09 | IMD-004 | H-07 — The legacy loop path is required by the bare in-memory core: pinned, not retired | implementation | accepted | `IMD-004` |
| 2026-10-09 | IMD-002 | Enum-driven event-kind mapping in the state snapshot | implementation | accepted | `IMD-002` |
| 2026-10-09 | AD-011 | Arch — The framework owns the pump, not the loop: the default agent is composition | architecture | accepted | `AD-011` |
| 2026-10-09 | AD-010 | Arch — The repo layout IS the boundary: dhc.framework (zero tools) vs dhc.tooling (the agent's composed world) vs dhc.ui (the operator's side) | architecture | accepted | `AD-010` |
| 2026-10-09 | AD-009 | Arch — Direct agent communication is framework; channels are tooling over the primitive | architecture | accepted | `AD-009` |
| 2026-10-09 | AD-008 | Arch — The artifact store is operator tooling, not framework: the seam stays, the storage moves to dhc.tooling | architecture | accepted | `AD-008` |
| 2026-10-09 | AD-007 | Single monotonic time base for all duration comparisons (H-04) | architecture | accepted | `AD-007` |
| 2026-10-08 | PD-001 | Parked-time semantics for the wall-clock ceiling: parked time is credited | product | accepted | `PD-001` |
| 2026-10-08 | IMD-003 | Token/cost accumulation at the driver seam | implementation | accepted | `IMD-003` |
| 2026-10-08 | IMD-001 | Agent module separation: loop, caps, integrity, and context triggers extracted from runtime.py | implementation | accepted | `IMD-001` |
| 2026-10-07 | TC-001 | IMP-001 — Adopted task contract (Phase 1 governance gate) | implementation | accepted | `TC-001` |
| 2026-10-07 | AD-006 | Event stream consumed in-loop (partial reversal of INFO-048) | architecture | accepted | `AD-006` |
| 2026-10-07 | AD-005 | Guardrails three-part placement | architecture | accepted | `AD-005` |
| 2026-10-07 | AD-004 | Default ships as fabrication kit | architecture | accepted | `AD-004` |
| 2026-10-07 | AD-003 | Op vocabulary split by cost | architecture | accepted | `AD-003` |
| 2026-10-07 | AD-002 | Four hard gates are pump behavior | architecture | accepted | `AD-002` |
| 2026-10-07 | AD-001 | Kernel made real | architecture | accepted | `AD-001` |
