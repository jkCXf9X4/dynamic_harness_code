---
id: EVAL-001
type: eval
title: Runtime architecture selection
summary: Thirteen requirement groups from the use cases reject every single-shape candidate; the fit is the minimal execution core — kernel, artifact data plane, boundary event log — with parent-wired channels and one agent-facing surface
date: 2026-10-06
status: draft
---

# Runtime architecture selection

The use cases (`INFO-002` … `INFO-044`) place thirteen requirement groups on
the runtime. Every classical architecture satisfies some and structurally fails
the rest; the requirements separate into planes whose seam the pre-studies
distilled (`INFO-042`, `INFO-043`).

## The requirement set

1. Isolated, killable execution unit per agent — `INFO-038`, `INFO-005`, `INFO-034`, `INFO-040`.
2. Private persistent REPL; explicit context in/out, never merged — `INFO-030`, `INFO-002`, `INFO-004`, `INFO-007`.
3. Recursive, unbounded delegation-as-code, uniform at every level — `INFO-004`, `INFO-010`, `INFO-019`.
4. Non-blocking spawn; await/poll/callback, callbacks serialized between parent actions — `INFO-009`, `INFO-013`, `INFO-031`, `INFO-032`, `INFO-033`, `INFO-039`.
5. Typed terminal states; failure shaped like success, escalating upward only — `INFO-005`, `INFO-011`, `INFO-020`, `INFO-032`.
6. Supervision: parent alive until children settle; parent death fails the subtree — `INFO-014`, `INFO-018`.
7. Immutable content-addressed artifacts, headline→summary→report pull — `INFO-006`, `INFO-012`, `INFO-017`.
8. Boundary-only provenance: five events, causal ids, DAG, payloads by reference — `INFO-027`, `INFO-043`.
9. Parent-wired channel topology: direct peer, rooms, sibling handoff, default group isolation — `INFO-015`, `INFO-016`, `INFO-018`, `INFO-009`.
10. One operator door at the root: streaming, mid-turn steering, routed questions, file-driven TUI — `INFO-017`, `INFO-022`, `INFO-023`, `INFO-028`.
11. Turn-as-code V-model: persisted-then-executed block, self-verify in-block — `INFO-002`, `INFO-003`.
12. Substrate stance: mid-run tool loading, public interface, embeddable, container-hosted — `INFO-007`, `INFO-041`, `INFO-044`, `INFO-025`, `INFO-008`.
13. Runtime-owned invisible instrumentation (rot detection, monitoring) — `INFO-021`, `INFO-007`.

## Candidates

- **Central graph orchestrator** — fails 3 and 9: delegation is agent-authored at run time (`INFO-004`, `INFO-018`), and a central graph rebuilds the tool-call loop `INFO-001` exists to eliminate.
- **Shared-state threads** — fails 1 (no fault containment), 2 (shared namespace), 4 (`INFO-033`'s serialization becomes global lock discipline).
- **Classic actor platform** — fits 1, 3, 6; but a REPL is a heavy long-lived interpreter, not a message handler, and 4, 7, 10 sit outside its vocabulary.
- **Task-graph futures runtime** — fits 3, 4, 5, 8; fails 1 (one blocking call freezes the loop), 2 (futures are one-shot), 6 (no supervision).
- **Blackboard / event-driven store** — fits 7, 8; fails 11 (the turn is imperative, not reactive), 4, 6.

No single shape covers the set; each fits one plane and breaks the others.

## Selection: minimal execution core, separated planes

- **Kernel (execution plane)** — the `INFO-043` contract made real: per-agent isolated unit (`INFO-038`) with private persistent REPL; a runtime-owned turn engine (persist-before-execute, LLM-call timeout `INFO-020`, steering injection `INFO-022`); task registry (`delegate` / `await` / `status` / `cancel`, typed terminal states); inter-action callback dispatch (`INFO-039`); supervision — parent death fails the subtree (`INFO-014`).
- **Data plane** — immutable content-addressed artifact store, three tiers (`INFO-006`); event payloads traced by reference (`INFO-027`).
- **Observability plane** — boundary-only event log: five events, causal ids, DAG (`INFO-027`, `INFO-043`); rot detection watches the stream from outside (`INFO-021`).
- **Interaction services** — channels wired per group by the delegating parent (`INFO-018`): parent-child, direct peer (`INFO-015`), rooms (`INFO-016`), operator door at the root only (`INFO-017`).
- **One agent-facing surface** — the injected `self` and free verbs (`INFO-029`) are the only door into the kernel, keeping the interface public and decoupled (`INFO-041`).

The defining property stays `INFO-042`'s: the kernel understands lifecycles
and boundaries, never code internals — the action space stays unconstrained
while the trace stays answerable.

## Fit check

| Requirement groups | Owning plane |
|---|---|
| 1, 2, 11 | kernel — turn engine |
| 3, 4, 5, 6 | kernel — task registry, supervision |
| 7 | data plane |
| 8, 13 | observability |
| 9, 10 | interaction services |
| 12 | surface, plus the `INFO-008` container boundary (orthogonal — it hosts any candidate) |

Every group maps to exactly one owner; no requirement is homeless.

## Left unpinned

- Thread-vs-process placement — stays with `INFO-038`; requirement 1 plus `INFO-040`'s hard kill point to process-backed units.
- Unifying `INFO-037` with the `INFO-029` surface — deferred by `INFO-037`; this selection assumes the surface is the sole door.
- Steering mechanics and first-turn gating — open in `INFO-029` (`INFO-022`, `INFO-019`).
- REPL checkpointing — optional in the source analysis; no current use case demands it.

## Owns
- The selected runtime architecture and its fit against the use-case requirements.

## Excludes
- The commitment to the execution-core contract — `INFO-037`.
- The design model, recommended contract, and capability surface — `INFO-042`, `INFO-043`, `INFO-029`.
- Per-agent placement — `INFO-038`; the hosting boundary — `INFO-008`.
