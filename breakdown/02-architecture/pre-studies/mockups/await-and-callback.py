"""One emitted block under the selected architecture (EVAL-001): a turn that
joins two children while a third settles mid-block. The block IS the action:
the runtime persists it, then executes it in this parent's REPL (INFO-002,
INFO-043); one function below is one block body — comments cite INFO-IDs.
"""

from dhc import *    # the task verbs stay free, task-first (INFO-029) —
                     # the boundary verbs ride self's stubs, CALL-shaped (INFO-042)


async def turn_join_and_drain():
    # scan / classify / rollup: handles an earlier turn's DELEGATE (INFO-009)
    # left in this REPL; rollup was spawned there with on_done=record —
    # the callback registration shape is unpinned (INFO-033)
    
    scan, classify, rollup = self.children

    r1 = await scan.result()       # AWAIT: block until terminal (INFO-031)
    r2 = await classify.result()   # fork/join: fan out, run, join (INFO-009)

    # rollup settled while the block was blocked in the awaits: its callback
    # queued as an event, dispatched between this block's own actions
    # (INFO-039) — drained here, at an action boundary, never concurrent
    for ev in self.drain():                  # arrived events, completion order
        if not ev.ok:                       # one shape, success or failure
            return self.fail(f"{ev.child}: {ev.reason}")                # INFO-011
        tail = ev.artifacts[0].read(size=4_000)    # sync paginated pull — the
                                                   # pair's output side, rehydrated

    r3 = await rollup.result()     # still succeeds: ensure-terminal, not
                                  # first observation (INFO-031, INFO-033)
    out = self.publish(           # the block's act (INFO-006)
        headline=f"{sum(r.ok for r in (r1, r2, r3))}/3 children settled",
        summary=f"two joined on await; one drained ({len(tail)} lines)",
        report=(r1, r2, r3))    # the join's verdicts ride the report tier
    settled = sum(r.ok for r in (r1, r2, r3))
    if settled < 3:                        # authored in-block (INFO-003) —
        return self.fail("children unsettled")   # the check is the branch
    return self.complete(headline=out.headline, artifacts=[[out.id]])
