"""One agent turn's emitted block under the selected architecture (EVAL-001).

Per INFO-002 the block IS the action: the runtime persists it, then executes
it against the agent's persistent REPL — persist-before-execute is runtime
mechanics, visible here only as a comment. From the agent's side the block
reads its task context off the injected `self` (read-only: id, requirement,
acceptance, channels — INFO-029, INFO-003), makes one sync tool call,
self-verifies the result — no FAIL lines in the capped output — reports.
"""

from dhc.tools import bash    # concrete tools import per-run (INFO-007, INFO-044)


async def turn_hello():
    # self is injected (INFO-029 draft) — the sketch of what it carries: _support.py
    tid, req = self.id, self.requirement       # context off self (INFO-003)

    out = self.tool(bash, f"pytest -q {tid}")   # sync; the ONE tool call —
    hits = out.search("FAILED", limit=5)           # full output persists as
    log = out.read(size=4_000)                     # an artifact; a handle back

    if hits:                              # failure = success shape
        return self.fail(f"pytest failures: {', '.join(hits)}")           

    art = self.publish(headline=f"{tid}: pytest result",
                       summary=log, report=None)    # the report tier rides
    # tenant-less for now — the two-tier `text=` probe is recorded in
    # mockups/README.md (INFO-006)
    return self.complete(headline= "Job done", artifacts=[[art.id]])


# INFO-004 — a requirement too big for one call decomposes instead: the same
# block shape, spawn + await where tool sits.
