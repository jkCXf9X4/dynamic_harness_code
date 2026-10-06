"""One agent turn under the selected architecture (EVAL-001): cancel a straggler.

Per INFO-002 the runtime persists this block, then executes it on the agent's
persistent REPL (INFO-030). `self` is the injected read-only task context
(INFO-003). Every operation is a free verb taking the value acted on as its
first argument (INFO-029): status, cancel, and result take the task; read
takes the handle; verify takes the value verified; publish takes the acting
agent.
"""

from dhc import *    # the verb library — extension is new verbs (INFO-029)


async def turn_cancel_a_straggler():
    # `children` is REPL-bound — the previous turn's spawns (INFO-030)
    states = {k: status(k) for k in children}    # sync, non-blocking (INFO-043)

    hung = next(k for k, s in states.items() if not s.done)      # one hangs
    cancel(hung, reason="straggler")         # INFO-034 — the worker is
    # terminated; unpublished partial work dies with it (INFO-040)

    # INFO-005 — the cancelled result is typed like any other: .ok / .reason /
    # .artifacts. Awaiting it settles immediately; no third terminal shape.
    outcome = await result(hung)
    assert not outcome.ok and outcome.reason == "cancelled"
    salvaged = read(outcome.artifacts[0], size=4_000)   # only published work
                                                        # survives (INFO-006)
    # a child that failed on its own — same shape, for contrast (INFO-005)
    failed = next(k for k, s in states.items() if s.done and not s.ok)
    crashed = await result(failed)
    assert not crashed.ok and crashed.reason != "cancelled"

    report = publish(self, headline="2 settled, 1 cancelled, 1 failed",
                     summary="straggler killed; survivors in the report")
    verify(self, against=self.acceptance,       # INFO-003 — value-first: the
           results=[outcome, crashed])          # block's self-verify, last
                                                # action before it settles
    return complete(self, headline=report.headline,
                    artifacts=[[report.id, salvaged.id]])
