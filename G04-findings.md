# G-04 — Settled-event access as a workspace tool

**Branch:** `g04-events-tool` · **Worktree:** `.dynamic-harness/261008_223605_2752/wt/g04`
**Closes:** vision gap A7 (INFO-053) — "event consumption: which settled events the agent reads, and when" is under agent control.

## Problem

Today the agent reaches its settled-event stream only through the default
runner's `observe` call (`fabrication.py` `make_observe` → `context.py`
`observe_digest`) or by rewriting the runner. There is no `events` name in the
core namespace (`runtime.py` `_build_namespace`), so *choosing* a consumption
schedule requires rewriting the runner. The runtime already exposes
peek+cursor semantics (`Runtime.events`, `runtime.py:631`), but that surface
is the default runner's, not a first-class agent tool.

## Design

Expose settled-event access as the **12th workspace tool** (`events`),
registered like the other 11 in `tools.py`. The tool wraps the runtime's
existing event stream — it does **not** build a second event path.

- **`Runtime.tool_events(agent_id)`** (new, additive): the same
  non-destructive `events:<id>` peek fan-out seam as `Runtime.events`, but
  with the *tool's own* per-agent cursor (`_tool_event_cursors`). This keeps
  the agent's consumption independent of the default runner's `observe`
  (`_event_cursors`) and the caps watchdog (`_caps_cursors`) — matching the
  codebase's established multi-consumer pattern (the drain-race fix). The
  discipline guarantees (FIFO, at-most-once, persist-before-execute) remain
  runtime-owned: the tool only advances a read cursor over the
  already-persisted, ordered stream.
- **`_events(ctx)`** in `tools.py`: wraps `ctx.runtime.tool_events(ctx.agent_id)`.
  Registered in `_TOOL_NAMES` and `_bind`, so it is injected into the
  workspace namespace and reachable from both action blocks and
  agent-authored runners (the namespace is merged into the workspace each
  turn; the runner's globals = workspace + kit).

**Why a separate cursor (not reusing `Runtime.events`):** the default runner's
`observe()` already consumes via `_event_cursors`. If the tool shared that
cursor, the agent's own reads would steal events from the default loop's
digest (and vice versa). A dedicated cursor lets the agent consume on its own
schedule without interfering — the whole point of A7.

## Files changed (all additive — 57 insertions, 0 deletions)

| File | Change |
|---|---|
| `src/dhc/agent/runtime.py` | +`_tool_event_cursors` dict; +`tool_events()` method (mirrors `events()`) |
| `src/dhc/agent/tools.py` | +`_events()` tool; +`"events"` in `_TOOL_NAMES` and `_bind` |
| `tests/agent/test_tools.py` | +`"events"` to the `TOOL_NAMES` set (additive — the installed tool set grew by one) |
| `tests/agent/test_events_tool.py` | **new** — 4 tests |

## Tests added (`tests/agent/test_events_tool.py`)

1. `test_events_tool_consume_once` — the tool returns the agent's settled
   events with a consume-once cursor (2nd call empty; new event picked up on
   the 3rd).
2. `test_events_tool_cursor_independent_of_observe` — the tool's cursor is
   independent of the default runner's `observe` cursor (no stealing either
   way).
3. `test_events_tool_fifo_order` — events returned in FIFO (publish) order.
4. `test_agent_reads_events_on_own_schedule` — **non-default consumption
   pattern**: an agent replaces its `__runner` with one that reads events
   **twice per turn** (the default reads once per turn via `observe`) on its
   own schedule, and completes normally. Asserts the first read each turn is
   non-empty and the second is empty (consume-once holds).

## Acceptance criteria

1. **Tool gives the agent its own settled events with a consume-once cursor,
   without rewriting the runner.** PASS — `events()` tool;
   `test_events_tool_consume_once` + `test_agent_reads_events_on_own_schedule`.
2. **A test exercises a non-default consumption pattern (agent reads events on
   its own schedule) and completes normally.** PASS —
   `test_agent_reads_events_on_own_schedule` (reads twice per turn, completes).
3. **Discipline unchanged: FIFO, at-most-once, persist-before-execute tests
   still green.** PASS — `tests/agent/test_event_stream.py` 29 passed; full
   suite green.

## Deviations / notes

- **Baseline was red for an environmental reason, not a code regression.**
  The full suite at HEAD: 423 passed, 1 failed —
  `tests/llm/test_fabrication.py::test_value_demo_runs_unmodified` fails with
  `ModuleNotFoundError: No module named 'dhc'` because it spawns a subprocess
  that cannot import the src-layout `dhc` package (not installed; no
  `PYTHONPATH`). With `PYTHONPATH=src` it passes. This is exactly the
  "PYTHONPATH fallback" the worktree protocol's step 5 anticipates for test
  isolation. All test runs in this worktree use `PYTHONPATH=src`.
- **True baseline:** 424 tests green with `PYTHONPATH=src` (423 direct + 1
  subprocess test).
- **Roadmap citation drift:** none material. The roadmap's `runtime.py:631-656`
  for `Runtime.events` and `tools.py:251-288` for registration are accurate at
  HEAD `25bab3d`.
- `test_tools.py`'s `TOOL_NAMES` set was updated **additively** (one name
  added) because `test_list_tools` asserts the exact installed tool set; this
  grows the set, it does not weaken the test.
