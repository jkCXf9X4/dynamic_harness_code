"""One agent turn's emitted block under the selected architecture (EVAL-001).

Per INFO-002 the block IS the action: the runtime persists it, then executes
it against the agent's persistent REPL — persist-before-execute is runtime
mechanics, visible here only as a comment. From the agent's side the block
reads its task context off the injected `self` (read-only: id, requirement,
acceptance, channels — INFO-029, INFO-003), makes one sync tool call,
self-verifies the result — no FAIL lines in the capped output — reports.
"""

from _support import *

from dhc import *    # Worker is a spec value, not a built-in (INFO-007)
from dhc.tools import bash    # concrete tools import per-run (INFO-007, INFO-044)



async def turn_hello(self : Agent):
    # self is injected (INFO-029 draft) — the sketch of what it carries: _support.py

    out = self.tool(bash, "pytest -q")  # sync; the ONE tool call —
    
    hits = out.search("FAILED", limit=5)  # ranked hits; full output persists as
    log = out.read(size=4_000)  # an artifact; a handle back

    art = self.publish(
        headline=f"{self.id}: pytest result", summary=log, report=None
    )  # the report tier rides

    if hits:  # failure = success shape
        return self.fail(f"pytest failures: {', '.join(line for _, line in hits)}")

    return self.complete(
        headline=art.headline,  # uniform with the siblings —
        artifacts=[[out.id, art.id]],
    )  # provenance pair (INFO-027)


# INFO-004 — a requirement too big for one call decomposes instead: the same
# block shape, spawn + await where tool sits.
