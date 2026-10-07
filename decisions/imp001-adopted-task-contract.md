---
id: imp001-adopted-task-contract
type: contract
title: "IMP-001 — Adopted task contract (Phase 1 governance gate)"
date: 2026-10-07
status: adopted
imp: IMP-001
---

# IMP-001 — Adopted task contract

This contract is the governance gate for injecting IMP-001 ("Agent-owned
executor — the REPL as the main loop") into the `dhc` package. It refines the
IMP's 6-step task-contract seed into concrete file-level tasks with per-step
acceptance criteria, grounded in the actual code at HEAD
(`5e94ff4`, working tree clean, 341 tests).

**Phase 1 (this commit) is documentation only.** The decision records
`0001`–`0006` lock the scoping decisions D1–D5 and the INFO-048 partial
reversal. No code changes begin until this contract is adopted and committed.

## Non-negotiable gates (apply to every step)

1. **341-test baseline green at every step** — `python3 -m pytest -q` must
   pass after each step; no existing test is modified to accommodate the
   injection.
2. **Default fabrication is the ONLY execution path** — backward
   compatibility is "the default fabrication" (D4), never a second loop.
3. **`examples/value_demo.py` passes unmodified** on the default loop.
4. **No new dependencies**; Python 3.10 (`python3`).
5. **Never `git add -A` / `git add .`** — stage only the intended files
   explicitly.
6. **Do NOT modify `breakdown/` spec leaves** (INFO-xxx) in this IMP's code
   steps; breakdown-state adoption is a separate owning-layer step on
   adoption.
7. **Do NOT modify `dhc/`, `tests/`, `examples/` in Phase 1** — this contract
   is committed before any code change.

## Code-surface map (grounded in HEAD)

| Module | Current state (verified) | Change |
|---|---|---|
| `dhc/repl.py` (176 lines) | `ReplEngine` with `execute`/`reset`/`globals_for`/`has_workspace`, per-agent lock, timeout containment via daemon thread + snapshot rollback (INFO-020), `result` slot | Add resumable-run primitives (`install`/`advance`/`inject`/`suspend`/`resume`/`kill`), `run_block`, per-advance snapshot; keep `execute` for the default path |
| `dhc/runtime.py` (552 lines) | `_worker_loop` (fixed loop: stop-flag → driver → `engine.execute` → consume events → settle), blocking `await_`, `_build_namespace`, `_settle` (at-most-once), `_drain_completions`, `_wait_children_settled`, `cancel` | `_worker_loop` → `_pump_agent` (install fabrications, advance one step, classify, gates + caps watchdog, per-step events); completion dispatch stays on the existing dispatcher |
| `dhc/driver.py` (211 lines) | `LLMDriver.__call__` (line 86), `_recent_context` (line 146, `limit=5`, 200 chars) — the lossy-context pain | `__call__` becomes the default `decide(context)` fabrication; prompt assembly becomes a fabrication; rot observation moves into the default loop's observe step |
| `dhc/wiring.py` (394 lines) | Composition root, `_ReplEngineAdapter` (line 175) translating the Result-returning contract, `_extend_namespace`, `register_default_tools` | Inject the fabrication kit into the namespace; expose `run_block`/`context`/channels as workspace citizens; `ensure_fabrication`; keep the in-code surface (INFO-041) stable on the default loop |
| `dhc/config.py` | `Settings` dataclass; `HarnessConfig`/`SafetyConfig` (Pydantic) | Settings gain ceiling-cap defaults (wall-clock, steps, workspace bytes, children, messages) |
| `dhc/operator.py` / `dhc/cli.py` | `Operator` (root door, `DefaultDriver`), CLI rendering | Read-only `inspect(agent_id)` window into a live workspace |
| `dhc/agent.py` | `Agent` surface (spawn/publish/complete/fail/cancel/status/result/tool/await_/poll/children_of) | Keep the in-code surface stable on the default loop; fabrication kit rides the namespace |
| `dhc/event_stream.py` | Unchanged discipline (FIFO, at-most-once, persist-before-execute) | Only consumption moves into the loop (INFO-048 partial reversal, record `0006`) |

## The 6 steps

### Step 1 — ReplEngine resumable-run primitives

**Files to change:** `dhc/repl.py`; new tests in `tests/test_repl.py`.

**What to add/change:**
- `install(agent_id, generator)` — register a resumable generator as the
  agent's `__runner` (replaces the per-turn `execute` path for pumped agents).
- `advance(agent_id, timeout)` — run one yield-window of the installed
  generator in a daemon thread with `join(step_timeout)`; on timeout, roll
  back the workspace to the per-advance snapshot and **abandon** the
  generator (never resume it); return the yielded value or a contained
  failure.
- `inject(agent_id, namespace)` — merge caller namespace into the workspace
  (the existing `execute` merge, reused).
- `suspend(agent_id)` / `resume(agent_id)` / `kill(agent_id)` — lifecycle
  control between steps (cancellation lands between steps, INFO-040).
- `run_block(code, timeout)` — non-locking nested exec honoring the outer
  step budget (documented: a runaway nested block is caught only by the outer
  step timeout).
- Per-advance snapshot (the shallow-copy mechanism of INFO-020, now per-step
  instead of per-turn).
- `execute` retained unchanged for the default path (back-compat).

**New tests:** install/advance returns yielded values; advance timeout →
rollback + generator abandoned (a second advance raises/returns contained
failure, never resumes); `run_block` nested exec; `execute` still passes its
existing tests unchanged.

**Acceptance criteria:** all existing `tests/test_repl.py` pass unmodified;
new primitives covered; `python3 -m pytest -q` green (341+).

### Step 2 — Fabrication kit (default `__runner` + `decide`)

**Files to change:** `dhc/driver.py`, `dhc/wiring.py`, `dhc/agent.py`; new
tests in `tests/test_repl.py` / `tests/test_runtime.py`.

**What to add/change:**
- Default `__runner` generator that reproduces today's turn loop exactly
  (decide → run_block → consume events → settle).
- `decide(context)` fabrication wrapping the current LLM/Mock brain;
  `driver.__call__` becomes the default `decide`; `_turns`/`_calls`
  bookkeeping moves into workspace state.
- Fabrication kit injected into the namespace: `run_block`, `context`
  (guardrails/inbox/outbox/budgets/digests), channel handles (`messenger`,
  `room`, `escalate`, `ask`), checkpoint/rollback/compact helpers, caps view.
- `ensure_fabrication` re-seeds any fabrication the agent broke or deleted
  (e.g. `__runner = 42` → re-seed default; event emitted).

**New tests:** default loop reproduces MockDriver behavior; `__runner = 42`
re-seeds; deleted `context` re-seeds; default loop is None-safe.

**Acceptance criteria (backward-compat gate D4):** the `MockDriver`
integration suite and `examples/value_demo.py` pass **unmodified** on the
default loop; `python3 -m pytest -q` green.

### Step 3 — `_pump_agent` under the four hard gates

**Files to change:** `dhc/runtime.py`; new tests in `tests/test_runtime.py`.

**What to add/change:**
- `_worker_loop` → `_pump_agent`: install fabrications, advance one step,
  classify the yield (settle/wait/sleep), run the four hard gates (D2):
  settlement at-most-once (INFO-046), crash containment (INFO-005), outer
  ceiling caps, cancellation grace (INFO-040).
- Emit per-step events; completion dispatch stays on the existing dispatcher
  (INFO-047) — `_settle`, `_drain_completions`, `_wait_children_settled`
  unchanged in behavior.
- Caps watchdog: wall-clock, step count, workspace bytes, child count,
  message rate (defaults from `config.py`).

**New tests:** runaway loop (`while True: pass`) contained (timeout →
rollback → reset or settle) with mesh alive; child-count cap forced stop;
settlement still at-most-once; cancellation grace → `kill()` + rollback +
settle.

**Acceptance criteria:** all existing `tests/test_runtime.py` and
`tests/test_integration.py` pass unmodified; four-gate behavior covered;
`python3 -m pytest -q` green.

### Step 4 — `yield Await/Poll/Sleep` servicing

**Files to change:** `dhc/runtime.py`; new tests in `tests/test_runtime.py`.

**What to add/change:**
- Pump services `yield Await(handle)` / `yield Poll(handle)` /
  `yield Sleep(t)` and completion wakeups with park/resume.
- A parent can `yield Await(child)` **without consuming step budget** (D3) —
  the trampoline's core win over blocking `await_` (INFO-031).

**New tests:** slow-child test proving the parent thread is not starved while
awaiting a child; `yield Sleep` parks and resumes; `yield Poll` non-blocking.

**Acceptance criteria:** parent-thread-starvation removed (slow-child test
passes); `await_` still works on the default loop; `python3 -m pytest -q`
green.

### Step 5 — Context/guardrail surface + `ensure_fabrication` + caps watchdog + `operator.inspect`

**Files to change:** `dhc/config.py`, `dhc/operator.py`, `dhc/cli.py`,
`dhc/wiring.py`; new tests in `tests/test_config.py`, `tests/test_operator.py`.

**What to add/change:**
- `config.py`: ceiling-cap defaults (wall-clock, steps, workspace bytes,
  children, messages) on `Settings` / `HarnessConfig`/`SafetyConfig`.
- Guardrail surface per D5: normative (visible context-in at delegation),
  operational tripwires (pump-evaluated between steps), reactions
  (completion-style events on the parent's stream, executed in the parent's
  REPL).
- `ensure_fabrication` (re-seeds broken fabrications) — completes Step 2's
  seam.
- Caps watchdog digest (reportable).
- `operator.inspect(agent_id)` — read-only window into a live workspace
  (full transparency, D2).

**New tests:** caps defaults present and enforced; `operator.inspect` returns
a read-only view; guardrail tripwire fires between steps; reaction ships as a
completion-style event to the parent.

**Acceptance criteria:** all existing `tests/test_config.py`,
`tests/test_operator.py` pass unmodified; new surface covered;
`python3 -m pytest -q` green.

### Step 6 — Acceptance fixture

**Files to change:** new tests (e.g. `tests/test_imp001_acceptance.py`); no
changes to existing tests.

**What to add/change:**
- A fixture agent that replaces `__runner`, injects messages/guardrails,
  awaits a child without burning step budget, and runs a runaway loop that is
  contained (timeout → rollback → reset or settle) with the mesh alive.

**New tests:** the acceptance fixture above, exercising D1–D5 end to end.

**Acceptance criteria:** the fixture passes; the full suite
(`python3 -m pytest -q`) is green at 341+ tests; `examples/value_demo.py`
still passes unmodified; the mesh stays alive through every containment
scenario in the IMP's containment table.

## Risks carried into the contract

- **Generator thread affinity** — an abandoned generator is never resumed
  (the old thread mutates only the discarded snapshot dict); sequential
  join-ordered advances are safe. Made explicit in Step 1.
- **Nested exec reentrancy** — `run_block` bypasses the per-agent lock at a
  deeper level; a runaway nested block is caught only by the outer step
  timeout. Documented in Step 1.
- **Determinism** — custom loops break scripted-driver tests unless policies
  default to the fabrications; fixtures must swap `__runner`/`decide` as
  cells (Step 2 gate).
- **Open questions** (tracked in the IMP, not blocking): exact ceiling-cap
  defaults; whether `yield Await` replaces `await_` at the surface or
  coexists; whether the pump runs per-agent-thread (INFO-038) or per-advance;
  whether the hard-gate count stays exactly four.

## Breakdown-state adoption (owning layers, on adoption — NOT this contract's code steps)

- Revise INFO-001 (rot instrumentation invisible-by-default, authorable by
  explicit opt-in), INFO-050 (the REPL owns the loop and its lifecycle),
  INFO-051 (event-stream consumption in-loop, discipline runtime-owned).
- INFO-048 partial reversal recorded in decision record `0006`.
- Promote INFO-037 from uncommitted to the realized kernel contract; extend
  INFO-021 so rot response policy can ride the new guardrail/reaction surface.
- INFO-049's boundary log remains the provenance backbone unchanged.
- Move IMP-001 to `06-evolution/implemented/` on adoption.