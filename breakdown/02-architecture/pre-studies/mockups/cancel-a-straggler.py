"""Cancel a straggler: one turn kills a hung child and contrasts it with one
that failed on its own."""

from _support import *

from dhc import *
from dhc.tools import bash


async def turn_cancel_a_straggler(self : Agent):
    states = {c: c.status() for c in self.children}

    hung = next(c for c, s in states.items() if not s.done)
    hung.cancel(reason="straggler")

    outcome = await hung.result()
    assert not outcome.ok and outcome.reason == "cancelled"
    salvaged = outcome.artifacts[0]

    failed = next(c for c, s in states.items() if s.done and not s.ok)
    crashed = await failed.result()
    assert not crashed.ok and crashed.reason != "cancelled"

    report = self.publish(headline="2 settled, 1 cancelled, 1 failed",
                          summary="straggler killed; survivors in the report",
                          report=None)
    if (sum(s.ok for s in states.values()) != 2
            or outcome.reason != "cancelled"):
        return self.fail("survivors unsettled or straggler uncancelled")
    return self.complete(headline=report.headline,
                         artifacts=[[report.id, salvaged.id]])
