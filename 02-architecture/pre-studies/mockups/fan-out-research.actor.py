"""Contrast mockup for INFO-037's deferred unification (EVAL-001): the same
fan-out scenario as the task-handle mockup, written against a classic
actor-message style instead of the INFO-029 surface — no task handles; the
mailbox is the interface; ask/tell to actor identities.
"""

# Same requirement + acceptance criteria as the handle mockup (INFO-003);
# only the interaction style differs. Four parallel children on a complicated
# problem; the parent keeps working between receives, collects as they settle.

kids = [spawn(Worker, requirement=self.requirement,   # no parent argument —
              acceptance=self.acceptance)             #   parenthood is implicit
        for _ in range(4)]                            #   (INFO-014): pids only

collected, failed = [], []
for _ in range(4):                        # parent keeps working between
    match receive(timeout=30):            #   receives — no await/status/cancel
        case Ask(peer, q):                # one mailbox is one door: the operator
            tell(peer, Reply(ok=True, artifacts=[self.spec]))  # door (INFO-017)
                                              #   is sender-matching, no own home
        case Reply(ok=True, artifacts=arts):
            collected += arts              # payloads, not handles — the
                                           # content-addressed store (INFO-006)
                                           #   sits outside the vocabulary
        case Reply(ok=False, reason=why):  # failure shaped like success —
            failed.append(why)             #   same .ok/.reason/.artifacts (INFO-005)

publish(self, headline=f"{len(collected)}/4 subtasks", report=collected)
# friction: publish is an INFO-029 verb — the actor style reaches outside its
# vocabulary for the artifact plane (INFO-006, INFO-012); `self` stays, as the
# actor's address carrying the read-only task context; no persisted turn block
# to self-verify in-block (INFO-002) — the style makes that analog impossible.
