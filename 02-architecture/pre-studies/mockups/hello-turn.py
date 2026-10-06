"""One agent turn's emitted block under the selected architecture (EVAL-001).

Per INFO-002 the block IS the action: the runtime persists it, then executes
it against the agent's persistent REPL — persist-before-execute is runtime
mechanics, visible here only as a comment. From the agent's side the block
reads its task context off the injected `self` (read-only: id, requirement,
acceptance, channels — INFO-029, INFO-003), makes one sync tool call,
self-verifies the result against the parent's acceptance criteria, reports.
"""

from dhc import *    # free verbs; first arg = the value acted on (INFO-029)
from dhc.tools import bash


async def turn_hello():
    # self is injected (INFO-029 draft) — the sketch of what it carries: _support.py
    tid, req = self.id, self.requirement       # context off self (INFO-003)

    out = self.tool(bash, f"pytest -q {tid}")   # sync; the ONE tool call —
    hits = out.search("FAILED", limit=5)           # full output persists as
    log = out.read(size=4_000)                     # an artifact; a handle back

    verdict = out.verify(against=self.acceptance)  # INFO-003 — the in-block
                                                    # self-verify (proposed verb)
    if not verdict.ok:                              # failure = success shape
        return self.fail(verdict.reason)           # .ok/.reason/.artifacts

    art = self.publish(headline=f"{tid}: {verdict.headline}",
                  summary=log, report=verdict)      # content-addressed (INFO-006)
    return self.complete(headline= art.headline, artifacts= [[out.id, art.id]])


# INFO-004 — a requirement too big for one call decomposes instead: the same
# block shape, spawn + await where tool sits.
