---
id: IMP-001
type: imp
title: Agent-owned executor — the REPL as the main loop
summary: Turn the runtime's fixed loop into a workspace-owned resumable generator the agent authors and pumps under a small hard-gate layer — full transparency for context, guardrails, and experimentation, without taking the mesh down
date: 2026-10-07
status: current
pb_exempt: true
---

# Agent-owned executor — the REPL as the main loop

The committed runtime's agent loop (`_worker_loop` → `LLMDriver` → one
`ReplEngine.execute` per turn) is now a workspace-resident, agent-authored
**resumable generator** that the runtime *pumps* one yield-window at a time.
This is the "kernel made real" (`INFO-037`): the turn engine lives in the REPL
as a first-class workspace citizen, under a small, non-negotiable runtime gate
layer that keeps the mesh alive no matter what an agent does inside its own
workspace.

## Implemented

- **Status: implemented.** This IMP is adopted and in the code; it lives under
  `implemented/` as the historical record of what was scoped and done, and is
  no longer tracked as open work.
- **Decision records** `0001`–`0007` lock the scoping decisions D1–D5, the
  `INFO-048` partial reversal, and the agent-module separation; the adopted
  task contract is `imp001-adopted-task-contract`.
- **Code commits** `7832c45` → `54ed8db` (IMP-001 steps 1–6): resumable-run
  primitives, the fabrication kit, `_pump_agent` under the four hard gates,
  `yield Await/Poll/Sleep` servicing, the context/guardrail surface +
  `ensure_fabrication` + caps watchdog + `operator.inspect`, and the
  acceptance fixture.
- **Verification:** the acceptance fixture (`tests/test_imp001_acceptance.py`)
  exercises D1–D5 end to end; the full suite is green (416 tests at adoption).

## Why — pain and evidence

- **The model's context is lossy and runtime-squeezed.** `LLMDriver._build_prompt`
  feeds the model only the agent's requirement, acceptance, status and the last
  ~5 events (`LLMDriver._recent_context`, `limit=5`, 200 chars each), and
  `runtime.events` *drains* the stream — consumed events never come back. The
  persistent REPL workspace (`INFO-050`), which actually accumulates the
  agent's knowledge, is never summarized for the model. Rot economics from
  `INFO-001` (decomposed 3-turn workers beat a rotting monolith) are
  undermined by this gap: any multi-turn agent is working blind on its own
  history.
- **The loop is fixed.** Orchestration — decide the next block, run it, consume
  happenings, settle — is hard-coded in `Runtime._worker_loop` and
  `LLMDriver.__call__`. An agent cannot author, view, or replace its own loop,
  cannot inject guardrails from inside its own executing code, and cannot
  experiment with alternative control flow. All policy lives in runtime code.
- **Custom guardrails have no home.** Guardrail policy is per-delegation
  (response policy is the parent's job, excluded from `INFO-021`), but today
  there is no mechanism to inject *custom* guardrails "from `execute(code)` →
  `spawn(...)`" — only a hard-coded rot detector that logs and the one-size
  prompt.
- **Blocking supervision burns wall-clock.** `await_` (`INFO-031`) blocks the
  parent's worker thread; a slow child consumes the parent's turn/timeout
  budget for the entire wait.
- **`INFO-037` stays parked.** "The turn engine made real" is explicitly left
  uncommitted in `INFO-048`'s exclusions. This IMP is its realization.

## The proposed shape — kernel in user space

- Each agent's main loop is a **resumable generator** living in the agent's own
  workspace globals (`__runner`). The agent views, edits, and replaces it like
  any other variable it owns (`INFO-007` already treated tools this way; this
  treats orchestration the same).
- The runtime shrinks to a **pump**: advance the generator one yield-window
  (one *step*), classify what it yielded, enforce gates, repeat. The agent owns
  the orchestration intelligence; the pump owns preemption and integrity.
- **A yield is a checkpoint.** Between yields the workspace is consistent, so
  the pump snapshots cheaply (the shallow-copy mechanism of `INFO-020`, now
  per-step instead of per-turn); cancellation lands between steps; per-step
  budgeting becomes exact instead of per-turn.
- **Op vocabulary is split by cost.** Bounded, synchronous operations are
  direct workspace calls (`run_block(code)`, inbox.drain, messenger.send,
  guardrail/budget edits). Indefinite or off-thread operations are `yield`
  requests serviced by the pump: `yield Await(handle)`, `yield Poll(handle)`,
  `yield Sleep(t)`, and completion wakeups. A parent can `yield Await(child)`
  **without consuming step budget** — this is the trampoline's core win over
  blocking `await_` today.
- **Containment reuses the proven machinery.** Each advance runs in a daemon
  thread with `join(step_timeout)` and snapshot rollback on timeout (`INFO-020`);
  a timed-out generator is *abandoned*, never resumed. The workspace is the
  blast radius: a broken loop costs one agent, not the mesh (`INFO-005`,
  `INFO-038`).

## Decisions (reached during scoping)

### D1 — Resumable generator / trampoline as the executor foundation
**Choice.** Foundation is a resumable generator pumped by the runtime, not a
step-function invoked per tick and not the unchanged turn loop.
**Rationale.** Only a resumable runner gives the agent true authorship of the
whole loop while keeping preemption and per-step budgets in the runtime; yields
as checkpoints make snapshots, cancellation, and budget enforcement exact.
**Alternatives.** A runtime-pumped step-function (cadence stays runtime-owned,
weakens "full control"); keeping the current driver loop (the pain above
stands); a full interpreter rewrite with preemption at arbitrary points
(unsafe; the thread+snapshot net is already proven).

### D2 — Full transparency, bounded only by a hard-gate layer
**Choice.** The agent sees and may edit everything in its own workspace —
including its budgets, tripwires, guardrails, and the loop itself — apart from
four non-negotiable gates that are not variables but pump behavior: (1)
settlement at-most-once (`INFO-046`), (2) crash containment / blast radius
(`INFO-005`), (3) outer ceiling caps (wall-clock, step count, workspace size,
child count, message rate) enforced by the pump, (4) cancellation grace
(`INFO-040`).
**Rationale.** Maximum autonomous experimentation is the point of the change;
the gates guarantee a hostile or degrading workspace cannot take down the mesh.
Full transparency also kills the "injection channel" problem: there is no
separate channel for messages/guardrails/context because the agent *is* the
loop and reads/edits those as ordinary data.
**Alternatives.** Layered visibility (normative open, operational digest) —
safer, but leaves a runtime-squeezed read model and re-creates an injection
mechanism; rejected in favor of transparency for this candidate.

### D3 — Bounded-sync vs yield-async op split
**Choice.** Direct workspace calls for bounded synchronous ops; `yield`
requests only for indefinite/off-thread ops (`Await`, `Poll`, `Sleep`,
completion wakeups).
**Rationale.** Keeps the generator simple to author, keeps the pump's contract
tiny, and eliminates the parent-thread-starvation failure of blocking `await_`
(`INFO-031`) — waiting on a child no longer consumes a parent's step budget.
**Alternatives.** Yield everything (an over-typed request vocabulary; harder to
author); call everything directly (blocking supervision burns budgets again).

### D4 — Deterministic default fabrications; driver becomes `decide`
**Choice.** Every workspace is born with a fabrication kit whose defaults
replicate today's behavior exactly: default `__runner`, `decide(context)`
(which wraps the current LLM/Mock brain), `run_block`, `context`
(guardrails/inbox/outbox/budgets/digests), channel handles
(`messenger`, `room`, `escalate`, `ask`), checkpoint/rollback/compact helpers,
and a visible caps view. `driver.__call__` becomes the default `decide`
fabrication; its bookkeeping (`_turns`, `_calls`) moves into workspace state.
`ensure_fabrication` re-seeds any fabrication the agent broke or deleted.
**Rationale.** The `MockDriver` suite and operator/root door keep their
contracts and determinism on the default loop; backward compatibility is
"the default fabrication," not a second execution path.
**Alternatives.** No default (agents must bootstrap a loop; breaks all existing
tests); a separate legacy path in parallel (two loops to maintain).

### D5 — Guardrail placement: authored in the REPL, bound at spawn, enforced by the pump
**Choice.** Guardrails decompose into (a) *normative* constraints the child
should internalize — parent-imposed ones arrive as visible context-in at
delegation (`INFO-050`), self-authored ones are ordinary workspace data; (b)
*operational* tripwires (rot threshold, budgets, forced compaction,
termination) evaluated by the pump between steps and visible/editable to the
agent except where they meet the ceiling caps; (c) *reactions* (terminate,
re-decompose, signal parent) shipped as completion-style events on the parent's
stream and executed in the parent's REPL — the `INFO-033`/`INFO-047` pattern.
**Rationale.** The parent is the decomposition owner (`INFO-004`); its reaction
must run in the parent, never in the child. The pump, not agent code, owns
enforcement timing so a degrading agent cannot silently skip a tripwire at the
ceiling.
**Alternatives.** All guardrails inside agent code (a degrading agent defeats
its own leash); all guardrails at spawn as static params (no evolution of
policy mid-run, no custom hooks).

## What was changed

### Code surface (implementation layer)

| Module | Change |
|---|---|
| `repl.py` | `ReplEngine` gained resumable-run primitives: `install`/`advance`/`inject`/`suspend`/`resume`/`kill`; `run_block` (non-locking nested exec honoring the outer step budget); per-advance snapshot; generator abandoned on timeout; `execute` retained for the default path. |
| `runtime.py` | `_worker_loop` became `_pump_agent`: install fabrications, advance one step, classify (settle/wait/sleep), run gates and caps watchdog, emit per-step events; completion dispatch stays on the existing dispatcher (`INFO-047`). |
| `driver.py` | `__call__` became the default `decide(context)` fabrication; prompt assembly became a fabrication; rot observation moved into the default loop's observe step. |
| `agent.py` / `wiring.py` | Inject the fabrication kit into the namespace; expose `run_block`, `context`, channels as workspace citizens; `ensure_fabrication`; keep the in-code surface (`INFO-041`) stable on the default loop. |
| `event_stream.py` | Unchanged discipline (FIFO, at-most-once, persist-before-execute); only consumption moved into the loop — a deliberate, partial `INFO-048` reversal (placement, not discipline). |
| `config.py` | Settings gained ceiling-cap defaults (wall-clock, steps, workspace bytes, children, messages). |
| `operator.py` / `cli.py` | Read-only `inspect(agent_id)` window into a live workspace (full transparency makes this legitimate). |

### Breakdown state (owning layers, on adoption)

- Revised `INFO-001` (rot instrumentation invisible-by-default, authorable by
  explicit opt-in), `INFO-050` (the REPL owns the loop and its lifecycle),
  `INFO-051` (event-stream consumption in-loop, discipline runtime-owned).
- Recorded the `INFO-048` partial reversal in decision record `0006` —
  consumption moves into the loop, the reason for the original ruling
  (interpreter-level locks, private namespace) survives because discipline
  stays external.
- Promoted `INFO-037` from uncommitted to the realized kernel contract this IMP
  makes real; extended `INFO-021` so rot response policy can ride the new
  guardrail/reaction surface instead of only logging.
- `INFO-049`'s boundary log remains the provenance backbone unchanged; per-step
  events flow through it as before.

## Containment — experiment and fail without taking the mesh down

| Agent does | What happens | Mesh |
|---|---|---|
| Loop raises at a yield | Contained Result; agent (by its own policy) falls back to the default loop or settles failed | up |
| Loop never yields (`while True: pass`) | Step timeout → snapshot rollback → generator abandoned; pump resets from checkpoint or settles | up |
| Installs `__runner = 42` | `ensure_fabrication` re-seeds the default; event emitted | up |
| `while True: spawn(...)` | child-count cap hits the outer ceiling → forced stop | up |
| Edits own budgets/tripwires | ceilings still bind; watchdog digest still reportable | up |
| Deletes `context` / breaks fabrications | `ensure_fabrication` re-seeds on demand; default loop is None-safe | up |
| Ignores cancellation | cancellation grace → `kill()` + rollback + settle (`INFO-040`) | up |

## Risks and open questions

- **Generator thread affinity.** An abandoned generator is never resumed (the
  old thread mutates only the discarded snapshot dict), so sequential
  join-ordered advances are safe; made explicit in the contract.
- **Nested exec reentrancy.** `run_block` bypasses the per-agent lock at a
  deeper level; a runaway nested block is caught only by the outer step
  timeout — documented.
- **Observability.** Bespoke loops are harder to read than one uniform loop;
  per-step events + the boundary log (`INFO-049`) + `operator.inspect` mitigate.
- **Trust model.** This legitimizes what arbitrary `exec` already permits;
  subprocess isolation per agent (`INFO-038`) is the future hardening lever for
  untrusted runs.
- **Determinism.** Custom loops break scripted-driver tests unless policies
  default to the fabrications; fixtures swap `__runner`/`decide` as cells.
- **Open.** Exact ceiling-cap defaults; whether `yield Await` replaces
  `await_` at the surface or coexists; whether the pump runs per-agent-thread
  (`INFO-038`) or per-advance; whether the hard-gate count stays exactly four.

## Owns
- The agent-owned executor: resumable-generator loop in the REPL, the pump, the
  four hard gates, the fabrication kit (defaults, decide, context, channels,
  checkpoint helpers, caps), and the record of its adoption ripple
  (`INFO-001`, `INFO-037`, `INFO-048`, `INFO-050`, `INFO-051`).

## Excludes
- Guardrail *content* and reaction policy semantics — owned by the delegation
  contract (`INFO-004`) and rot detection (`INFO-021`).
- Per-agent subprocess isolation — `INFO-038`; future hardening, not this IMP.
- External memory/RAG incorporation — `INFO-044`.
- Backward-compat and determinism of the default loop — a gate on this IMP,
  owned by the test surface.
