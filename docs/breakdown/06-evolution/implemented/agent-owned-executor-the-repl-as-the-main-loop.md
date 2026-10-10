---
id: IMP-001
type: imp
title: Agent-owned executor — the REPL as the main loop
summary: Workspace-owned resumable generator replaces the runtime's fixed loop — the agent authors and pumps it under a small hard-gate layer; full transparency for context, guardrails, and experimentation; mesh stays up
date: 2026-10-07
status: current
pb_exempt: true
---

# Agent-owned executor — the REPL as the main loop

The committed runtime agent loop is `_worker_loop`, then `LLMDriver`, then one
`ReplEngine.execute` per turn. It is now a workspace-resident, agent-authored
**resumable generator**. The runtime *pumps* it one yield-window at a time. This
is the "kernel made real" (`INFO-037`). The turn engine lives in the REPL as a
first-class workspace citizen. It sits under a small, non-negotiable runtime gate
layer. The gate layer keeps the mesh alive no matter what an agent does inside
its own workspace.

## Implemented

- **Status: implemented.**
  - This IMP is adopted and in the code.
  - It lives under `implemented/` as the historical record of what was scoped and done.
  - It is no longer tracked as open work.

- **Decision records.**
  - `AD-001`–`AD-006` and `IMD-001` lock the scoping decisions D1–D5.
  - They lock the `INFO-048` partial reversal.
  - They lock the agent-module separation.
  - The adopted task contract is `TC-001`.

- **Code commits** `7832c45` to `54ed8db` (IMP-001 steps 1–6).
  - Resumable-run primitives.
  - The fabrication kit.
  - `_pump_agent` under the four hard gates.
  - `yield Await/Poll/Sleep` servicing.
  - The context/guardrail surface.
  - `ensure_fabrication`.
  - Caps watchdog.
  - `operator.inspect`.
  - The acceptance fixture.

- **Verification.**
  - The acceptance fixture (`tests/test_imp001_acceptance.py`) exercises D1–D5 end to end.
  - The full suite is green (416 tests at adoption).

## Why — pain and evidence

- **The model's context is lossy and runtime-squeezed.**
  - `LLMDriver._build_prompt` feeds the model only the agent's requirement, acceptance, status.
  - It feeds also the last ~5 events (`LLMDriver._recent_context`, `limit=5`, 200 chars each).
  - `runtime.events` *drains* the stream.
  - Consumed events never come back.
  - The persistent REPL workspace (`INFO-050`) accumulates the agent's knowledge.
  - The model never gets a summary of it.
  - Rot economics from `INFO-001`: decomposed 3-turn workers beat a rotting monolith.
  - This gap undermines those economics.
  - Any multi-turn agent works blind on its own history.

- **The loop is fixed.**
  - Orchestration is hard-coded in `Runtime._worker_loop` and `LLMDriver.__call__`.
  - Orchestration: decide the next block, run it, consume happenings, settle.
  - An agent cannot author, view, or replace its own loop.
  - It cannot inject guardrails from inside its own executing code.
  - It cannot experiment with alternative control flow.
  - All policy lives in runtime code.

- **Custom guardrails have no home.**
  - Guardrail policy is per-delegation.
  - Response policy is the parent's job, excluded from `INFO-021`.
  - Today no mechanism injects *custom* guardrails from `execute(code)` to `spawn(...)`.
  - Only a hard-coded rot detector that logs exists.
  - The one-size prompt also exists.

- **Blocking supervision burns wall-clock.**
  - `await_` (`INFO-031`) blocks the parent's worker thread.
  - A slow child consumes the parent's turn/timeout budget for the entire wait.

- **`INFO-037` stays parked.**
  - "The turn engine made real" is explicitly left uncommitted in `INFO-048`'s exclusions.
  - This IMP is its realization.

## The proposed shape — kernel in user space

- Each agent's main loop is a **resumable generator**.
  - It lives in the agent's own workspace globals (`__runner`).
  - The agent views, edits, and replaces it like any other variable it owns.
  - `INFO-007` already treated tools this way.
  - This treats orchestration the same way.

- The runtime shrinks to a **pump**.
  - The pump advances the generator one yield-window (one *step*).
  - It classifies what the generator yielded.
  - It enforces gates.
  - It repeats.
  - The agent owns the orchestration intelligence.
  - The pump owns preemption and integrity.

- **A yield is a checkpoint.**
  - Between yields the workspace is consistent.
  - The pump snapshots cheaply (the shallow-copy mechanism of `INFO-020`).
  - Snapshotting is now per-step instead of per-turn.
  - Cancellation lands between steps.
  - Per-step budgeting becomes exact instead of per-turn.

- **Op vocabulary is split by cost.**
  - Bounded, synchronous operations are direct workspace calls.
  - Direct calls: `run_block(code)`, `inbox.drain`, `messenger.send`, guardrail/budget edits.
  - Indefinite or off-thread operations are `yield` requests serviced by the pump.
  - Yield requests: `yield Await(handle)`, `yield Poll(handle)`, `yield Sleep(t)`, completion wakeups.
  - A parent can `yield Await(child)` **without consuming step budget**.
  - That is the trampoline's core win over blocking `await_` today.

- **Containment reuses the proven machinery.**
  - Each advance runs in a daemon thread with `join(step_timeout)`.
  - Snapshot rollback runs on timeout (`INFO-020`).
  - A timed-out generator is *abandoned*, never resumed.
  - The workspace is the blast radius.
  - A broken loop costs one agent, not the mesh (`INFO-005`, `INFO-038`).

## Decisions (reached during scoping)

### D1 — Resumable generator / trampoline as the executor foundation

- **Choice.**
  - Foundation is a resumable generator pumped by the runtime.
  - Not a step-function invoked per tick.
  - Not the unchanged turn loop.
- **Rationale.**
  - Only a resumable runner gives the agent true authorship of the whole loop.
  - It keeps preemption and per-step budgets in the runtime.
  - Yields as checkpoints make snapshots, cancellation, and budget enforcement exact.
- **Alternatives.**
  - A runtime-pumped step-function.
    - Cadence stays runtime-owned.
    - Weakens "full control".
  - Keeping the current driver loop.
    - The pain above stands.
  - A full interpreter rewrite with preemption at arbitrary points.
    - Unsafe.
    - The thread+snapshot net is already proven.

### D2 — Full transparency, bounded only by a hard-gate layer

- **Choice.**
  - The agent sees and may edit everything in its own workspace.
  - That includes its budgets, tripwires, guardrails, and the loop itself.
  - Exception: four non-negotiable gates.
  - The gates are not variables but pump behavior.
  - (1) Settlement at-most-once (`INFO-046`).
  - (2) Crash containment / blast radius (`INFO-005`).
  - (3) Outer ceiling caps enforced by the pump: wall-clock, step count, workspace size, child count, message rate.
  - (4) Cancellation grace (`INFO-040`).
- **Rationale.**
  - Maximum autonomous experimentation is the point of the change.
  - The gates guarantee a hostile or degrading workspace cannot take down the mesh.
  - Full transparency also kills the "injection channel" problem.
  - There is no separate channel for messages/guardrails/context.
  - The agent *is* the loop.
  - The agent reads/edits those as ordinary data.
- **Alternatives.**
  - Layered visibility (normative open, operational digest): safer.
  - But it leaves a runtime-squeezed read model.
  - It re-creates an injection mechanism.
  - Rejected in favor of transparency for this candidate.

### D3 — Bounded-sync vs yield-async op split

- **Choice.**
  - Direct workspace calls handle bounded synchronous ops.
  - `yield` requests handle only indefinite/off-thread ops.
  - Yield kinds: `Await`, `Poll`, `Sleep`, completion wakeups.
- **Rationale.**
  - Keeps the generator simple to author.
  - Keeps the pump's contract tiny.
  - Eliminates the parent-thread-starvation failure of blocking `await_` (`INFO-031`).
  - Waiting on a child no longer consumes a parent's step budget.
- **Alternatives.**
  - Yield everything: an over-typed request vocabulary, harder to author.
  - Call everything directly: blocking supervision burns budgets again.

### D4 — Deterministic default fabrications; driver becomes `decide`

- **Choice.**
  - Every workspace is born with a fabrication kit.
  - Kit defaults replicate today's behavior exactly.
  - Kit contents:
    - Default `__runner`.
    - `decide(context)`, which wraps the current LLM/Mock brain.
    - `run_block`.
    - `context`: guardrails/inbox/outbox/budgets/digests.
    - Channel handles: `messenger`, `room`, `escalate`, `ask`.
    - Checkpoint/rollback/compact helpers.
    - A visible caps view.
  - `driver.__call__` becomes the default `decide` fabrication.
  - Its bookkeeping (`_turns`, `_calls`) moves into workspace state.
  - `ensure_fabrication` re-seeds any fabrication the agent broke or deleted.
- **Rationale.**
  - The `MockDriver` suite keeps its contracts and determinism on the default loop.
  - The operator/root door keeps its contracts and determinism on the default loop.
  - Backward compatibility is "the default fabrication," not a second execution path.
- **Alternatives.**
  - No default: agents must bootstrap a loop.
    - That breaks all existing tests.
  - A separate legacy path in parallel: two loops to maintain.

### D5 — Guardrail placement: authored in the REPL, bound at spawn, enforced by the pump

- **Choice.**
  - Guardrails decompose into three classes.
  - (a) *Normative* constraints the child should internalize.
  - Parent-imposed ones arrive as visible context-in at delegation (`INFO-050`).
  - Self-authored ones are ordinary workspace data.
  - (b) *Operational* tripwires: rot threshold, budgets, forced compaction, termination.
  - The pump evaluates them between steps.
  - They are visible/editable to the agent except where they meet the ceiling caps.
  - (c) *Reactions*: terminate, re-decompose, signal parent.
  - They ship as completion-style events on the parent's stream.
  - They execute in the parent's REPL.
  - That is the `INFO-033`/`INFO-047` pattern.
- **Rationale.**
  - The parent is the decomposition owner (`INFO-004`).
  - Its reaction must run in the parent, never in the child.
  - The pump, not agent code, owns enforcement timing.
  - So a degrading agent cannot silently skip a tripwire at the ceiling.
- **Alternatives.**
  - All guardrails inside agent code.
    - A degrading agent defeats its own leash.
  - All guardrails at spawn as static params.
    - No evolution of policy mid-run.
    - No custom hooks.

## What was changed

### Code surface (implementation layer)

- **`repl.py`.**
  - `ReplEngine` gained resumable-run primitives: `install`/`advance`/`inject`/`suspend`/`resume`/`kill`.
  - Added `run_block`: non-locking nested exec honoring the outer step budget.
  - Per-advance snapshot.
  - Generator abandoned on timeout.
  - `execute` retained for the default path.
- **`runtime.py`.**
  - `_worker_loop` became `_pump_agent`.
  - `_pump_agent` installs fabrications.
  - It advances one step.
  - It classifies: settle/wait/sleep.
  - It runs gates and caps watchdog.
  - It emits per-step events.
  - Completion dispatch stays on the existing dispatcher (`INFO-047`).
- **`driver.py`.**
  - `__call__` became the default `decide(context)` fabrication.
  - Prompt assembly became a fabrication.
  - Rot observation moved into the default loop's observe step.
- **`agent.py` / `wiring.py`.**
  - They inject the fabrication kit into the namespace.
  - They expose `run_block`, `context`, channels as workspace citizens.
  - They provide `ensure_fabrication`.
  - They keep the in-code surface (`INFO-041`) stable on the default loop.
- **`event_stream.py`.**
  - Discipline unchanged: FIFO, at-most-once, persist-before-execute.
  - Only consumption moved into the loop.
  - That is a deliberate, partial `INFO-048` reversal.
  - The reversal is placement, not discipline.
- **`config.py`.**
  - Settings gained ceiling-cap defaults: wall-clock, steps, workspace bytes, children, messages.
- **`operator.py` / `cli.py`.**
  - Read-only `inspect(agent_id)` window into a live workspace.
  - Full transparency makes this legitimate.

### Breakdown state (owning layers, on adoption)

- **Revised `INFO-001`.**
  - Rot instrumentation invisible-by-default, authorable by explicit opt-in.
- **Revised `INFO-050`.**
  - The REPL owns the loop and its lifecycle.
- **Revised `INFO-051`.**
  - Event-stream consumption in-loop.
  - Discipline runtime-owned.
- **Recorded the `INFO-048` partial reversal in decision record `AD-006`.**
  - Consumption moves into the loop.
  - The original ruling reason survives: interpreter-level locks, private namespace.
  - It survives because discipline stays external.
- **Promoted `INFO-037` from uncommitted to the realized kernel contract this IMP makes real.**
- **Extended `INFO-021`.**
  - Rot response policy can ride the new guardrail/reaction surface.
  - Instead of only logging.
- **`INFO-049`'s boundary log remains the provenance backbone unchanged.**
  - Per-step events flow through it as before.

## Containment — experiment and fail without taking the mesh down

- **Loop raises at a yield.**
  - Contained Result.
  - The agent, by its own policy, falls back to the default loop or settles failed.
  - Mesh stays up.
- **Loop never yields (`while True: pass`).**
  - Step timeout.
  - Then snapshot rollback.
  - Then generator abandoned.
  - The pump resets from checkpoint or settles.
  - Mesh stays up.
- **Installs `__runner = 42`.**
  - `ensure_fabrication` re-seeds the default.
  - Event emitted.
  - Mesh stays up.
- **`while True: spawn(...)`.**
  - Child-count cap hits the outer ceiling.
  - Then forced stop.
  - Mesh stays up.
- **Edits own budgets/tripwires.**
  - Ceilings still bind.
  - Watchdog digest still reportable.
  - Mesh stays up.
- **Deletes `context` or breaks fabrications.**
  - `ensure_fabrication` re-seeds on demand.
  - Default loop is None-safe.
  - Mesh stays up.
- **Ignores cancellation.**
  - Cancellation grace.
  - Then `kill()`, rollback, settle (`INFO-040`).
  - Mesh stays up.

## Risks and open questions

- **Generator thread affinity.**
  - An abandoned generator is never resumed.
  - The old thread mutates only the discarded snapshot dict.
  - So sequential join-ordered advances are safe.
  - Made explicit in the contract.
- **Nested exec reentrancy.**
  - `run_block` bypasses the per-agent lock at a deeper level.
  - A runaway nested block is caught only by the outer step timeout.
  - Documented.
- **Observability.**
  - Bespoke loops are harder to read than one uniform loop.
  - Mitigations: per-step events, the boundary log (`INFO-049`), `operator.inspect`.
- **Trust model.**
  - This legitimizes what arbitrary `exec` already permits.
  - Subprocess isolation per agent (`INFO-038`) is the future hardening lever for untrusted runs.
- **Determinism.**
  - Custom loops break scripted-driver tests unless policies default to the fabrications.
  - Fixtures swap `__runner`/`decide` as cells.
- **Open.**
  - Exact ceiling-cap defaults.
  - Whether `yield Await` replaces `await_` at the surface or coexists.
  - Whether the pump runs per-agent-thread (`INFO-038`) or per-advance.
  - Whether the hard-gate count stays exactly four.

## Owns

- **The agent-owned executor.**
  - Resumable-generator loop in the REPL.
  - The pump.
  - The four hard gates.
  - The fabrication kit: defaults, decide, context, channels, checkpoint helpers, caps.
  - The record of its adoption ripple (`INFO-001`, `INFO-037`, `INFO-048`, `INFO-050`, `INFO-051`).

## Excludes

- **Guardrail *content* and reaction policy semantics.**
  - Owned by the delegation contract (`INFO-004`).
  - Owned by rot detection (`INFO-021`).
- **Per-agent subprocess isolation.**
  - `INFO-038`.
  - Future hardening, not this IMP.
- **External memory/RAG incorporation.**
  - `INFO-044`.
- **Backward-compat and determinism of the default loop.**
  - A gate on this IMP.
  - Owned by the test surface.
