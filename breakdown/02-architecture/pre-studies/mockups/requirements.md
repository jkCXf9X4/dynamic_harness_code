# Mockup requirements

The requirements the pre-study mockups read against, moved out of the code so
the sketches read clean. Every mockup sketches EVAL-001's selected
architecture and is a sketch, not the surface: trivial bodies are deliberate,
the shape is the annotation. Shared requirements apply to every scenario
mockup; each section below adds that file's own on top. `_support.py` sketches
the shapes; the scenario files sketch turns against them.

## Shared — every scenario mockup

- **The block IS the action** — the runtime persists the emitted block, then
  executes it against the agent's persistent REPL; persist-before-execute is
  runtime mechanics, visible in a sketch only as its absence (INFO-002).
- **A too-big requirement decomposes** — the same block shape, spawn + await
  where the tool call sits (INFO-004).
- **Injected `self`** — the read-only task context: id, requirement,
  acceptance (the parent's criteria), channels (INFO-029 draft, INFO-003).
- **Verbs ride the boundary CALL-shaped** — `tool` and `publish` are the
  injected context's stubs, `read` dispatches on the outcome handle; the
  boundary log, the artifact store, and the queue are runtime mechanics and
  stay comments (INFO-042, INFO-027).
- **One tool call** — `tool` is the ONE sync call at the boundary; the
  callable comes first (INFO-029).
- **Worker and tools** — `Worker` is a spec value, not a built-in; concrete
  tools import per-run (INFO-007, INFO-044).
- **One result shape** — failure is the success shape: `fail`, `complete`,
  and a cancelled child all settle the same Status; there is no third
  terminal (INFO-011, INFO-005).
- **Self-verify in-block** — the check is the branch, the reason is the
  block's own formatted string (INFO-003).
- **Provenance by reference** — artifacts ride as content-addressed id pairs,
  never inline (INFO-027).
- **Child-handle verbs extend the convention** — children are Agents too
  (INFO-043): status, result, and cancel ride their handles, cancel takes
  `reason=`; they extend INFO-029's free-verb convention, never invented
  silently.

## The shapes — `_support.py`

- **Content-addressed handles** — git-style sha1, not security: identical
  content is one artifact.
- **Agent ids are uuid, not content** — agents are execution, not content;
  identical requirements are distinct agents. Unique across REPLs, thread or
  process (INFO-038): OS entropy, no counter to lock. Minted once at birth,
  frozen with the handle; never derived, never recomputed.
- **Artifact tiers** — one published finding: headline / summary / report;
  the verdict itself rides the report tier (INFO-006).
- **Status** — the one shape, peek to terminal: `done` is the poll's
  predicate (INFO-043); the settled payload rides behind it (INFO-031),
  uniform across verbs and contexts — the context's own in `value`,
  provenance in `artifacts`; until `done`, the payload fields stay empty.
- **Event** — one arrived event: a settled Status tagged with its child
  (INFO-039) — who the event is about, the callback's payload.
- **EventStream** — one agent's stream, the channel completions ride
  (INFO-046); intake is typed to the terminal — only a Status enters
  (INFO-045). The general event loop polls it outside run_code; the REPL
  never polls or drains it.
- **register** — registration by held handle (INFO-045): an agent registers
  its own stream, a child's via its spawn handle, a peer's only via a wired
  channel (INFO-018). The callback runs in the registrant's REPL between
  its own actions, never concurrently (INFO-033).
- **ToolOutput** — the result-side surface: the full output persisted as an
  artifact, a handle back; content-addressed, by-reference open form
  (INFO-027). `search` returns ranked hits — order of appearance stands in
  for rank; `read` is a size-capped pull of the report tier.
- **Agent members** — `children` holds the previous turn's spawn handles,
  REPL-bound (INFO-030); `events` is the agent's one channel (INFO-045),
  polled by the general event loop, never the REPL. The verbs stay free
  functions in the library; the attribute stubs only mark the boundary.
- **done / status** — the poll predicate and the sync, non-blocking peek
  (INFO-043); attribute read vs method is unpinned; the peek carries the
  terminal's own shape, payload still empty.
- **result** — await/settle (INFO-031).
- **cancel** — the cancelled result is typed like any other (INFO-034).
- **spawn** — the free verb takes the value acted on first: the parent
  (INFO-029). Children are Agents too: the handle members ride Agent
  (INFO-043). The optional completion hook (INFO-033) registers on the
  child's stream at spawn time — one callback serves success and failure,
  receives the settled Event, runs between this parent's own actions, never
  concurrently (INFO-039); the stream's one intake is the same register as
  handle-side (INFO-045).
- **bash** — a stand-in for `dhc.tools.bash`; fabricates the run's pytest
  tail, long enough that the size-capped read lands inside the warnings
  summary — the pagination gesture reads something.

## hello-turn.py — one turn, one tool call

- The block reads its task context off the injected `self`, makes one sync
  tool call, self-verifies — no FAILED hits in the capped output — reports.
- The full tool output persists as an artifact; `search` and `read` work the
  handle back.
- `publish`'s report tier rides; the complete's headline is uniform with the
  siblings'.

## await-and-callback.py — join two, settle one by callback

- The block joins two children by await while a third settles by callback
  mid-block.
- `record` is an earlier turn's callback, left in this REPL: an earlier turn
  registered it on rollup's stream by held handle (INFO-045); the general
  event loop dispatches it between this parent's own actions, never
  concurrently (INFO-033, INFO-039).
- The callback runs in this REPL — its writes are REPL state.
- A raising callback settles the parent's own boundary, not the child's
  (INFO-046).
- The callback's pull is sync and paginated — the pair's output side,
  rehydrated: settled values as data, never the stream (INFO-046).
- scan / classify / rollup are an earlier turn's DELEGATE handles, left in
  this REPL with `record` (INFO-009, INFO-045).
- await blocks until terminal (INFO-031); the two joins are fork/join —
  fan out, run, join (INFO-009).
- The straggler settles while the block is blocked in the awaits: the
  general event loop resolved its stream outside run_code, never in this
  REPL (INFO-045), and dispatched the callback between this block's own
  actions (INFO-039) — the callback did the settling, not the awaits below.
- The third await is ensure-terminal, not first observation (INFO-031,
  INFO-033).
- `publish` is the block's act (INFO-006); the join's verdicts ride the
  report tier.

## fan-out-research.py — spawn four, keep working, poll

- One requirement broadcast to four children (INFO-009, INFO-013): spawn
  returns child handles immediately, each with its own acceptance criterion.
- The parent keeps working: one more sync tool call, blocks briefly; the
  full output persists as a content-addressed artifact.
- Poll, don't await (INFO-013): a bounded poll with a sync pause between
  polls collects each child where ready; a settled `result()` returns at
  once.
- Self-verify: failed and cancelled children share the shape — the failure
  names the unsettled indices (INFO-011).
- The report tier is context-provided (INFO-003).

## fan-out-research.actor.py — contrast: actor-message style

- The same fan-out scenario as the handle mockup, written against a classic
  actor-message style instead of the INFO-029 surface: no task handles; the
  mailbox is the interface; ask/tell to actor identities (INFO-037's
  deferred unification, EVAL-001).
- Same requirement and acceptance criteria; only the interaction style
  differs (INFO-003).
- spawn takes no parent argument — parenthood is implicit, pids only
  (INFO-014).
- The parent keeps working between receives — no await, status, or cancel.
- One mailbox is one door: the operator door (INFO-017) is sender-matching,
  no own home.
- Replies carry payloads, not handles — the content-addressed store
  (INFO-006) sits outside the vocabulary.
- Failure is shaped like success — same `.ok` / `.reason` / `.artifacts`
  (INFO-005).
- Friction: `publish` is an INFO-029 verb — the actor style reaches outside
  its vocabulary for the artifact plane (INFO-006, INFO-012); `self` stays
  as the actor's address carrying the read-only task context; no persisted
  turn block to self-verify in-block (INFO-002) — the style makes that
  analog impossible.

## cancel-a-straggler.py — cancel a straggler

- The previous turn's spawns are REPL-bound Agent handles (INFO-030); the
  verbs they carry ride CALL-shaped (INFO-042).
- `status()` is sync and non-blocking (INFO-043).
- Cancel terminates the worker; unpublished partial work dies with it
  (INFO-034, INFO-040).
- The cancelled result is typed like any other — `.ok` / `.reason` /
  `.artifacts`; awaiting it settles immediately; no third terminal shape
  (INFO-005).
- Only published work survives (INFO-006).
- A child that failed on its own shares the shape, for contrast (INFO-005).
- The criterion is the evidence itself — the report tier rides tenant-less.
