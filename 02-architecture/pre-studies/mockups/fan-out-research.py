"""Fan-out research (INFO-009, INFO-013) under EVAL-001's selected
architecture: one turn mid-task spawns four children, keeps working,
then polls — no await. INFO-002: the block IS the action. INFO-029:
free verbs take the value acted on first — spawn's first arg is the parent.
"""

from dhc import *    # Worker is a spec value, not a built-in (INFO-007)
from dhc.tools import bash    # concrete tools import per-run (INFO-007, INFO-044)


async def turn_fan_out_research():
    # INFO-009 / INFO-013 — one requirement broadcast to four children; spawn
    # returns child handles immediately, with per-child acceptance criteria.
    children = [spawn(self, Worker, requirement=self.requirement,
                      acceptance=crit) for crit in self.acceptance]

    # The parent keeps working: one more sync tool call (INFO-002) — the
    # callable comes first (INFO-029); blocks briefly; the full output
    # persists as a content-addressed artifact.
    out = tool(self, bash, "make lint")

    # Poll, don't await (INFO-013): collect each child where ready.
    results = [None] * len(children)
    for _ in range(60):                            # bounded poll, still no await
        for i, c in enumerate(children):
            if results[i] is None and c.done:      # handle attribute (INFO-043)
                results[i] = result(c)             # settled: returns at once
        if all(r is not None for r in results):
            break
        time.sleep(0.5)                            # sync pause between polls

    if not all(r and r.ok for r in results):       # self-verify: failed and
        bad = [i for i, r in enumerate(results)    # cancelled share the shape
               if not (r and r.ok)]
        fail(self, f"children {bad} failed or never settled")   # INFO-011

    art = publish(self, headline=f"{sum(r.ok for r in results)}/{len(children)} settled",
                  summary="four-way fan-out, polled",
                  report=verdicts)                 # context-provided (INFO-003)
    return complete(self, headline=art.headline,   # typed success terminal —
                    artifacts=[[out.id, art.id]])   # uniform with fail (INFO-011)
