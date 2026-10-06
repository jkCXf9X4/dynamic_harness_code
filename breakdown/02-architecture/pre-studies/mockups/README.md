# Mockup verdicts

The pre-study's conclusions — what the sketches adopted, pinned, or left
open. `requirements.md` holds what each sketch must show; this file holds
what the pre-study concluded and what still owns no answer. Nothing here
is scrapped silently: every adopt / pin / candidate is inventoried below
and moves out only when a record claims the question.

The discussion rides on deprecated drafts (`EVAL-001`, `INFO-029`,
`INFO-042`, `INFO-043`, `INFO-037`) — nothing yet supersedes them, and the
verdicts below are evidence for that discussion, not adopted decisions.

## Verdicts

| Mockup | Scenario | Verdict |
|---|---|---|
| `hello-turn.py` | the base loop | fits — open `tool`, the check is the branch, typed `complete` |
| `fan-out-research.py` | fan-out + poll | fits — the ready-sweep is the authored check |
| `await-and-callback.py` | await + callback | fits — the join checks the tally; the callback settles mid-block |
| `cancel-a-straggler.py` | cancel a straggler | fits — cancelled typed like any terminal |
| `fan-out-research.actor.py` | contrast: actor style | task-handle surface reads better — directional only: the sketch borrows `spawn` and leaves `receive`/`tell` undefined, so the contrast is not controlled |

## Adopted

- **`verify` — scrapped.** One verb couldn't own checking — different
  criteria are fulfilled in different ways. The responsibility is the
  block's: authored in-block, the check is the branch, the reason is the
  block's formatted string (`INFO-003`). Never inventoried in
  `…verbs.md`; recorded here instead.
- **`tool` — adopted.** Callable-first, args and kwargs pass through; the
  boundary's calls ride CALL-shaped (`INFO-042`). Concrete tools import
  per-run from `dhc.tools` (`INFO-007`, `INFO-044`).
- **`read` — adopted, widened.** The size-capped pull stays on the result
  side; the same verb, free-form, is the artifact plane's pull — it
  rehydrates a provenance pair or bare reference, tiers on demand
  (`INFO-006`, `INFO-027`). The store behind it is runtime mechanics
  (`INFO-042`).
- **`complete` — adopted.** The typed success terminal, uniform with
  `fail`'s shape (`INFO-011`).

## Pinned

- **Provenance pairs** — artifacts entries are `(source, artifact)` pairs:
  the source is what the finding was derived from, the artifact the
  published finding (`INFO-027`). Source-first order; `hello-turn.py`,
  `cancel-a-straggler.py`, and `await-and-callback.py`'s derivation pairs
  all read it.
- **`done` reads as an attribute** — predicates read as attributes,
  actions ride CALL-shaped (`INFO-042`): `status()`, `result()`,
  `cancel()` are calls, `done` is a read. `INFO-043`'s sketch shows method
  syntax; the attribute wins — a peek is not an action.
- **`Status` is named `Result`** — the settled shape carries `INFO-048`'s
  name: only a frozen `Result` enters the stream, tagged with its child
  as an `Event` (`INFO-039`).

## Still unpinned

- `delegate(task, …)` vs `spawn(parent, …)` naming.
- `self.acceptance`'s per-child access name.
- `on_done=` registration mechanics — spawn-time on the child's stream.
- The `INFO-019` gate's "settles" wording.
- `fail`'s artifacts-by-reference form (`INFO-027`).
- `match` — confirmed in the pre-study's first pass, never sketched.

## Known unknowns

- **A blocking block starves callbacks.** The poll loop in
  `fan-out-research.py` sleeps synchronously inside the async block; the
  REPL thread stalls, and a registered callback — promised dispatch
  between the parent's own actions (`INFO-033`, `INFO-039`, `INFO-047`) —
  starves for the loop's duration. No mockup combines poll + callback,
  so it hides. Open: may a block block, and what does "between actions"
  mean while it does?
- **A raising callback settles — what?** `await-and-callback.py`'s
  `record` raises on a failed child; no record owns what a raising
  callback settles — the parent's own boundary, or nothing at all. Open
  until a record claims it.
- **The report-tier rule is contradicted in use.** `requirements.md`
  says the verdict rides the report tier (`INFO-006`), yet
  `hello-turn.py` and `cancel-a-straggler.py` publish `report=None`
  ("tenant-less") and return the verdict through the terminal. One of
  the two is wrong; open which.
- **Content ids are 8 hex.** `_support._content_id` truncates to 32 bits —
  collision territory around ~77k artifacts in a plane where peers
  address artifacts by content hash (`INFO-012`). Sketch-level; widen
  before any store exists.
