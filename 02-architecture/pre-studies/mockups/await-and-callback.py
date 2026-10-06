"""One emitted block under the selected architecture (EVAL-001): a turn that
joins two children while a third settles mid-block. The block IS the action:
the runtime persists it, then executes it in this parent's REPL (INFO-002,
INFO-043); one function below is one block body — comments cite INFO-IDs.
"""

from dhc import *    # free verbs, first arg = value acted on (INFO-029)


async def turn_join_and_drain():
    # scan / classify / rollup: handles an earlier turn's DELEGATE (INFO-009)
    # left in this REPL; rollup was spawned there with on_done=record —
    # the callback registration shape is unpinned (INFO-033)
    scan, classify, rollup = children

    r1 = await result(scan)       # AWAIT: block until terminal (INFO-031)
    r2 = await result(classify)   # fork/join: fan out, run, join (INFO-009)

    # rollup settled while the block was blocked in the awaits: its callback
    # queued as an event, dispatched between this block's own actions
    # (INFO-039) — drained here, at an action boundary, never concurrent
    for ev in drain(self):                  # arrived events, completion order
        if not ev.ok:                       # one shape, success or failure
            fail(self, f"{ev.child}: {ev.reason}")               # INFO-011
        tail = read(ev.artifacts[0], size=4_000)   # sync paginated pull

    r3 = await result(rollup)     # still succeeds: ensure-terminal, not
                                  # first observation (INFO-031, INFO-033)
    out = publish(self,           # the block's act (INFO-006)
        headline=f"{sum(r.ok for r in (r1, r2, r3))}/3 children settled",
        summary=f"two joined on await; one drained ({len(tail)} lines)",
        report=join_report)
    verify(out, against=self.acceptance)      # self-verify; against kwarg adopted
    return complete(self, headline=out.headline, artifacts=[[out.id]])
