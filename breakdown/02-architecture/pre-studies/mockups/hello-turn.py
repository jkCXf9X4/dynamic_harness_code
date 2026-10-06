"""One agent turn: read the task context, one tool call, self-verify, report."""

from _support import *

from dhc import *
from dhc.tools import bash


async def turn_hello(self : Agent):
    out = self.tool(bash, "pytest -q")

    hits = out.search("FAILED", limit=5)
    log = out.read(size=4_000)

    art = self.publish(
        headline=f"{self.id}: pytest result", summary=log, report=None
    )

    if hits:
        return self.fail(f"pytest failures: {', '.join(line for _, line in hits)}")

    return self.complete(
        headline=art.headline,
        artifacts=[[out.id, art.id]],
    )
