---
id: 0001
type: decision
title: "IMP-001 D1 — Resumable generator / trampoline as the executor foundation"
date: 2026-10-07
status: accepted
---

# D1 — Resumable generator / trampoline as the executor foundation

## Context

The committed runtime's agent loop is fixed: `Runtime._worker_loop` →
`LLMDriver` → one `ReplEngine.execute` per turn. Orchestration — decide the
next block, run it, consume happenings, settle — is hard-coded in runtime
code, so an agent cannot author, view, or replace its own loop, cannot inject
guardrails from inside its own executing code, and cannot experiment with
alternative control flow. All policy lives in runtime code.

IMP-001 proposes turning the turn engine into a workspace-resident,
agent-authored **resumable generator** (`__runner`) that the runtime *pumps*
one yield-window (step) at a time. The scoping question is which execution
foundation realizes this: a resumable generator, a runtime-pumped
step-function, the unchanged turn loop, or a full interpreter rewrite.

## Decision

The foundation is a **resumable generator / trampoline** pumped by the
runtime. Each agent's main loop is a generator living in the agent's own
workspace globals (`__runner`); the agent views, edits, and replaces it like
any other variable it owns. The runtime shrinks to a pump: advance the
generator one yield-window (one *step*), classify what it yielded, enforce
gates, repeat. A yield is a checkpoint — between yields the workspace is
consistent, so the pump snapshots cheaply (the shallow-copy mechanism of
INFO-020, now per-step instead of per-turn); cancellation lands between
steps; per-step budgeting becomes exact instead of per-turn.

Containment reuses the proven machinery: each advance runs in a daemon thread
with `join(step_timeout)` and snapshot rollback on timeout (INFO-020); a
timed-out generator is *abandoned*, never resumed. The workspace is the blast
radius: a broken loop costs one agent, not the mesh (INFO-005, INFO-038).

## Rationale

Only a resumable runner gives the agent true authorship of the whole loop
while keeping preemption and per-step budgets in the runtime. Yields as
checkpoints make snapshots, cancellation, and budget enforcement exact. The
thread + snapshot containment net is already proven in `ReplEngine` (per-agent
lock, daemon worker thread, `join(timeout)`, rollback to turn-start snapshot),
so the trampoline reuses machinery that exists rather than inventing new
preemption.

## Alternatives Considered

- **Runtime-pumped step-function** — cadence stays runtime-owned; weakens
  "full control" and re-creates the injection-channel problem. Rejected.
- **Keeping the current driver loop** — the pain (lossy context, fixed loop,
  no custom guardrails, blocking supervision) stands unchanged. Rejected.
- **Full interpreter rewrite with preemption at arbitrary points** — unsafe;
  the thread + snapshot net is already proven and cheaper. Rejected.

## Consequences

- `ReplEngine` gains resumable-run primitives: `install` / `advance` /
  `inject` / `suspend` / `resume` / `kill`, plus `run_block` (non-locking
  nested exec honoring the outer step budget) and per-advance snapshots;
  `execute` is retained for the default path.
- A generator that never yields (`while True: pass`) is contained by the step
  timeout → snapshot rollback → generator abandoned; the pump resets from
  checkpoint or settles.
- Generator thread affinity must be explicit in the contract: an abandoned
  generator is never resumed (the old thread mutates only the discarded
  snapshot dict), so sequential join-ordered advances are safe.
- Nested `run_block` reentrancy bypasses the per-agent lock at a deeper level;
  a runaway nested block is caught only by the outer step timeout — acceptable,
  must be documented.