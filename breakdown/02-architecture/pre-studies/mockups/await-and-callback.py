"""One emitted block: join two children by await while a third settles by
callback mid-block."""

from _support import *

from dhc import *
from dhc.tools import bash


tail = ""    # REPL state: the callback writes it, the block reads it


def record(ev : Event):
    global tail
    if not ev.ok:
        raise RuntimeError(f"{ev.child}: {ev.reason}")
    tail = read(ev.artifacts[0], size=4_000)


async def turn_join_and_settle(self : Agent):
    scan, classify, rollup = self.children

    r1 = await scan.result()
    r2 = await classify.result()

    # rollup settled while the block sat in the awaits above — the callback
    # did the settling; this await is ensure-terminal
    r3 = await rollup.result()

    out = self.publish(
        headline=f"{sum(r.ok for r in (r1, r2, r3))}/3 children settled",
        summary=f"two joined on await; one settled by callback ({len(tail)} lines)",
        report=(r1, r2, r3))
    settled = sum(r.ok for r in (r1, r2, r3))
    if settled < 3:
        return self.fail("children unsettled")
    return self.complete(headline=out.headline,
                         artifacts=[[child, out.id] for r in (r1, r2, r3)
                                    for _, child in r.artifacts])
