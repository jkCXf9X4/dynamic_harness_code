---
title: Interface mockups
summary: Small plausible sketches of one agent turn's emitted block under the selected architecture — what the code interface answers, and the verbs it still lacks
---

# Interface mockups

Discussion material for the deferred unification of the execution-core contract
(`INFO-043`) with the capability surface (`INFO-029`) — EVAL-001's largest open
point. Each mockup writes one scenario's turn against the selected
architecture (`EVAL-001`) in the `example.py` style, probes a known unknown,
and returns a verdict: **fits**, **needs new verb X**, or — for the contrast
mockup — which of two surfaces reads better for the same scenario.

## The mockups

| Mockup | Scenario | Verdict |
|---|---|---|
| `hello-turn.py` | the base loop — `INFO-002`, `INFO-003`, `INFO-004` | **adopted** — open `tool`, result-side `verify`, typed `complete` |
| `fan-out-research.py` | fan-out + poll — `INFO-009`, `INFO-013` | **adopted** — open `tool` (callable-first), typed `complete`; the ready-sweep stands in for `verify` |
| `await-and-callback.py` | await + callback — `INFO-031`, `INFO-033`, `INFO-039` | **adopted** — `verify(against=...)`, typed `complete`; `drain(agent)` still a candidate |
| `cancel-a-straggler.py` | cancel — `INFO-034`, `INFO-040`, `INFO-005` | **adopted** — `verify(against=...)` + typed `complete`; `cancel(task, reason=...)` stays a candidate, already verb-form |
| `fan-out-research.actor.py` | contrast: actor style for the same scenario — `INFO-037` | task-handle surface reads better |

## What the verdicts answer

- **`verify` — adopted**: receiver-style on the result, criteria from the
  injected context (`out.verify(against=...)`); three mockups carry it —
  the base loop adopted it, the join verifies its result, the straggler
  self-verifies with it.
- **`tool` — adopted in open form**: the callable comes first, args and
  kwargs pass through (`tool(self, bash, f"pytest -q {tid}")`), so the surface
  stays open for what can be done while the trace stays boundary-side —
  persist-before-execute plus the boundary log keep it answerable
  (`INFO-021`, `INFO-027`); concrete tools import per-run from `dhc.tools`
  (`from dhc.tools import bash` — `INFO-007`, `INFO-044`).
- **`search` / `match` / `read` — confirmed** as written: ranked hits,
  exact spans, size-capped pull; attribute syntax dispatches through the
  verb library.
- **`complete` — adopted**: the typed success terminal, uniform with
  `fail`'s shape; `artifacts=[[out.id, art.id]]` carries provenance pairs
  (`INFO-027`).
- **The unification note**: `cancel`'s method-vs-verb tension resolves the
  same way — `INFO-043` sketches Task methods, `INFO-029` rules verbs-only,
  and the fn-first pattern lands verbs.
- **Unpinned**: poll style (methods vs attribute reads),
  `delegate(task,…)` vs `spawn(parent, spec,…)`, `self.acceptance`'s
  per-child access name, `on_done=` registration, the `INFO-019` gate's
  "settles" wording, and `fail`'s artifacts-by-reference (`INFO-027`).
- **The contrast takeaway**: `complete`/`verify`/`search`/`read` are
  task-handle-side; the actor style still lacks them — ~4 new verbs vs
  `INFO-043`'s five-verb set.

The other three mockups adopt the same patterns — `tool` callable-first,
result-side `verify`, typed `complete`; the contrast keeps the actor style
untouched.

## The complement

`_support.py` sketches the shapes the turns read against — the injected
`self` (`Agent`: id, requirement, acceptance, channels, plus the verb
dispatch stubs), the result-side `ToolOutput` (`search`/`read`/`verify`),
and the typed terminals (`Verdict`, `Turn` — `fail` uniform with
`complete`). Runtime mechanics — persist-before-execute, the boundary log,
the artifact store — stay comments. It excludes the contract and the
surface themselves: INFO-043 and INFO-029 both still draft.

## Owns

- The mockup set: one scenario per file, each citing the use cases it exercises and the unknowns it probes.
- The verdict slots and the verbs they adopted — adopted rows recorded in the inventory (`…verbs.md`); remaining candidates listed for `INFO-029`'s extension convention, never invented silently.

## Excludes

- The contract and the surface themselves — `INFO-043`, `INFO-029`.
- The selection and its candidates — `EVAL-001`, `INFO-037`, `INFO-042`.
- The scenarios' requirements — one layer up in Product.

## Contents

<!-- pb:index:start -->

<!-- pb:index:end -->
