"""Contrast mockup: the same fan-out scenario written against a classic
actor-message style — no task handles; the mailbox is the interface; ask/tell
to actor identities."""

from _support import *

from dhc import *
from dhc.tools import bash


async def fan_out_research(self : Agent):
    kids = [self.spawn(requirement=self.requirement,
                       acceptance=self.acceptance)
            for _ in range(4)]

    collected, failed = [], []
    for _ in range(4):
        match receive(timeout=30):
            case Ask(peer, q):
                tell(peer, Reply(ok=True, artifacts=[self.spec]))
            case Reply(ok=True, artifacts=arts):
                collected += arts
            case Reply(ok=False, reason=why):
                failed.append(why)

    publish(self, headline=f"{len(collected)}/4 subtasks", report=collected)
