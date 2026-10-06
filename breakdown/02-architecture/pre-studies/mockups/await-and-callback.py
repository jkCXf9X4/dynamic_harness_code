"""One emitted block under the selected architecture (EVAL-001): a turn that
joins two children while a third settles by callback mid-block. The block IS
the action: the runtime persists it, then executes it in this parent's REPL
(INFO-002, INFO-043). record below is an earlier turn's callback, left in
this REPL; the async function is the block body — comments cite INFO-IDs.
"""

from _support import *

from dhc import *    # Worker is a spec value, not a built-in (INFO-007)
from dhc.tools import bash    # concrete tools import per-run (INFO-007, INFO-044)


tail = ""    # REPL state: the callback writes it, the block reads it


def record(ev : Event):
    """The completion callback — an earlier turn registered it on rollup's
    stream by held handle, rollup.events.register(record) (INFO-045); the
    general event loop dispatches it between this parent's own actions,
    never concurrently (INFO-033, INFO-039)."""
    global tail    # the callback runs in this REPL — its writes are REPL state
    if not ev.ok:    # one shape, success or failure (INFO-011) — a raising
        # callback settles the parent's own boundary, not the child's (INFO-046)
        raise RuntimeError(f"{ev.child}: {ev.reason}")
    tail = ev.artifacts[0].read(size=4_000)    # the sync paginated pull — the
    # pair's output side, rehydrated: settled values as data, never the stream (INFO-046)


async def turn_join_and_settle(self : Agent):
    # scan / classify / rollup: handles an earlier turn's DELEGATE (INFO-009)
    # left in this REPL, record with it (INFO-045)

    scan, classify, rollup = self.children

    r1 = await scan.result()       # AWAIT: block until terminal (INFO-031)
    r2 = await classify.result()   # fork/join: fan out, run, join (INFO-009)

    # rollup settled while the block was blocked in the awaits: the general
    # event loop resolved its stream — outside run_code, never in this REPL
    # (INFO-045) — and dispatched record between this block's own actions
    # (INFO-039): the callback did the settling, not the awaits below

    r3 = await rollup.result()     # ensure-terminal, not first observation:
                                  # record already settled it (INFO-031, 033)
    out = self.publish(           # the block's act (INFO-006)
        headline=f"{sum(r.ok for r in (r1, r2, r3))}/3 children settled",
        summary=f"two joined on await; one settled by callback ({len(tail)} lines)",
        report=(r1, r2, r3))    # the join's verdicts ride the report tier
    settled = sum(r.ok for r in (r1, r2, r3))
    if settled < 3:                        # authored in-block (INFO-003) —
        return self.fail("children unsettled")   # the check is the branch
    return self.complete(headline=out.headline, artifacts=[[out.id]])
