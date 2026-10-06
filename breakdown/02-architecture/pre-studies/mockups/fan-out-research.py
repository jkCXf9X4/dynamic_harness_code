"""Fan-out research: one turn mid-task spawns four children, keeps working,
then polls — no await."""

from _support import *

from dhc import *
from dhc.tools import bash

import time


async def turn_fan_out_research(self : Agent):
    children = [self.spawn(requirement=self.requirement, acceptance=crit)
                for crit in self.acceptance]

    out = self.tool(bash, "make lint")

    results = [None] * len(children)
    for _ in range(60):
        for i, c in enumerate(children):
            if results[i] is None and c.done:
                results[i] = c.result()
        if all(r is not None for r in results):
            break
        time.sleep(0.5)

    if not all(r and r.ok for r in results):
        bad = [i for i, r in enumerate(results) if not (r and r.ok)]
        return self.fail(f"children {bad} failed or never settled")

    art = self.publish(headline=f"{sum(r.ok for r in results)}/{len(children)} settled",
                       summary="four-way fan-out, polled",
                       report=results)
    return self.complete(headline=art.headline,
                         artifacts=[[out.id, art.id]])
