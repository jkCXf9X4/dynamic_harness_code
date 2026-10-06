"""One agent turn under the selected architecture (EVAL-001): cancel a straggler.

Per INFO-002 the runtime persists this block, then executes it on the agent's
persistent REPL (INFO-030). `self` is the injected read-only task context
(INFO-003). The adopted verbs ride the boundary CALL-shaped (INFO-042):
publish is self's stub; read dispatches on the outcome handle (INFO-027).
The children are Agents too — INFO-043's Task-method sketch: status, cancel,
and result ride their handles, cancel takes reason=; the free verbs they'd
extend stay INFO-029's convention, never invented silently.
"""

from _support import *

from dhc import *    # Worker is a spec value, not a built-in (INFO-007)
from dhc.tools import bash    # concrete tools import per-run (INFO-007, INFO-044)



async def turn_cancel_a_straggler(self : Agent):
    # `children` is REPL-bound — the previous turn's spawns (INFO-030):
    # Agent handles, the verbs they carry ride CALL-shaped (INFO-042)
    states = {c: c.status() for c in self.children}    # sync, non-blocking (INFO-043)

    hung = next(c for c, s in states.items() if not s.done)      # one hangs
    hung.cancel(reason="straggler")          # INFO-034 — the worker is
    # terminated; unpublished partial work dies with it (INFO-040)

    # INFO-005 — the cancelled result is typed like any other: .ok / .reason /
    # .artifacts. Awaiting it settles immediately; no third terminal shape.
    outcome = await hung.result()
    assert not outcome.ok and outcome.reason == "cancelled"
    salvaged = outcome.artifacts[0]   # only published work survives (INFO-006)

    # a child that failed on its own — same shape, for contrast (INFO-005)
    failed = next(c for c, s in states.items() if s.done and not s.ok)
    crashed = await failed.result()
    assert not crashed.ok and crashed.reason != "cancelled"

    report = self.publish(headline="2 settled, 1 cancelled, 1 failed",
                          summary="straggler killed; survivors in the report",
                          report=None)     # the criterion is the evidence itself —
                                           # the report tier rides tenant-less
    if (sum(s.ok for s in states.values()) != 2    # authored in-block
            or outcome.reason != "cancelled"):     # (INFO-003) — the criterion
        return self.fail("survivors unsettled or straggler uncancelled")
    return self.complete(headline=report.headline,
                         artifacts=[[report.id, salvaged.id]])
