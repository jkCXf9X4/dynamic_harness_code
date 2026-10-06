### DEPRICATED ###


"""Example turns against the INFO-029 capability surface.

Per INFO-002 one turn emits one Python block, and the block IS the
action: the runtime persists the block, wraps it in a coroutine on the
fresh subprocess's event loop, and executes it. Each function below is
one such block body — top-level await and return are available inside
it. Comments cite the use case each step fulfills. `self` is the injected
context: read-only task data only (identity, requirement, acceptance,
channels). Every operation is a free verb from the dhc library taking the
value acted on as its first argument — spawn's first argument is the parent
whose child is created; publish, tool, and ask take the acting agent.

Context-provided names (read-only, e.g. plan, spec, img,
peer_artifact_id) come from the encapsulated context (INFO-003).
"""

from dhc import *    # the verb library: free functions, first arg = value
                     # acted on — extension is new verbs, not method changes

# -- turn 1: a parent decomposes, supervises, aggregates, reports -------

async def turn_parent_decomposes():
    children = [
        await spawn(self,                # delegation is code (INFO-004)
            Worker,
            requirement=s.requirement,   # child context: allocated
            acceptance=s.criteria,       #   requirement + parent criteria
        )                                #   — nothing more (INFO-003)
        for s in plan.subtasks
    ]

    # INFO-014 — the parent stays alive until children settle; INFO-005 —
    # a crashed child surfaces here as a failed result, not a dead parent
    results = [await result(c) for c in children]

    if not all(r.ok for r in results):
        fail(self, f"subtask 2 unreachable: {results[1].reason}")  # INFO-011

    art = publish(self,                  # immutable, content-addressed (INFO-006)
        headline=f"{sum(r.ok for r in results)}/{len(results)} subtasks done",
        summary="two re-decomposed; detail in the report artifact",
        report=write_up,
    )
    return {"headline": art.headline, "artifacts": [art.id]}      # INFO-002


# -- turn 2: a worker reads big tool output without ingesting it --------

async def turn_worker_reads_big_output():
    out = tool(self, "shell", "make test")  # sync; full output persists as
                                            # an artifact; a handle returns
    hits = search(out, "FAILED", limit=5)   # ranked hits, not the whole log
    tail = lines(out, offset=-20, size=20)  # windowed read
    head = read(out, size=4_000)            # capped pull

    handoff = artifact(self, peer_artifact_id)  # pull a published artifact
                                                # by id (INFO-012)
    return {"headline": f"{len(hits)} failures", "artifacts": [out.id, handoff.id]}


# -- turn 3: direct channels and the operator door -----------------------

async def turn_direct_channels():
    peer = agent(self, "worker-7")                             # INFO-015
    reply = await request(peer, {"handoff": peer_artifact_id}, timeout=30)

    rm = room(self, "impl")                                    # INFO-016
    await post(rm, "spec frozen: " + spec.id)

    answer = await ask_operator(self, "which spec version?")   # INFO-023

    # INFO-022 — mid-turn steering: an operator message sent while this
    # turn is blocked in an await (e.g. the request above) wakes it.

    return {"headline": answer.headline, "artifacts": [reply.id]}


# -- extension: tools arrive as artifacts, not built-ins -----------------

async def turn_extension():
    upscale = self.load_tool("upscale-v2")    # INFO-007 — capability from
                                              # an artifact
    out = upscale(img.id, scale=2)            # same contract: sync, handle back
    return {"headline": "upscaled", "artifacts": [out.id]}


# Agent kinds are values, not built-ins (INFO-007): the harness ships none,
# and these read as if defined by agent code. The spec is what the agent IS —
# behavior and defaults; the task args are what it is ASKED; the receiver and
# channels are where it SITS. Verbs are free functions — spawn's first
# argument is the parent whose child is created. The runtime builds ctx the
# same way for every kind, so authored kinds need no runtime changes.
Worker   = Agent()
Verifier = Agent()


# -- turn 4: multi-level organization, level by level (INFO-018) ---------

async def turn_set_up_groups():
    # The root spawns leads; each lead's own turn (not shown) spawns its
    # workers the same way. The root assigns each LEAD its group's structure;
    # a child receives exactly those channels and nothing more.
    review_room = room(self, "review")    # lookup-or-create; vocabulary unpinned
    triage = await spawn(self, Worker,    # fan-out only: no channels — results
        requirement=...,                  # route up point-to-point (INFO-009);
        acceptance=...,                   # siblings cannot address each other
    )
    review = await spawn(self, Worker,
        requirement=...,
        acceptance=...,
        channels=[review_room],           # a shared room (INFO-016) — exactly
    )                                     # this, nothing else, is visible
    chained = await spawn(self, Worker,
        requirement=...,
        acceptance=...,
        channels=[room(self, "handoff")], # a handoff pipeline: each stage posts
    )                                     # its output where the next reads (INFO-012)

    # The lead finds its channels in its context (access name unpinned) and
    # hands the same room down: channels=self.channels. Escalation is not a
    # group channel: a worker's self.fail routes to its parent regardless of
    # structure (INFO-011). Supervision repeats per level (INFO-014, INFO-005).
    # The org's shape is observable like any artifact (INFO-017):
    org = publish(self, headline="3 groups", summary="fan-out / room / chain",
                  report=full_wiring)
    return {"headline": org.headline, "artifacts": [org.id]}


# -- turn 5: the whole hierarchy in one action (INFO-019) ----------------

async def turn_set_whole_hierarchy():
    # INFO-019 — one action establishes every level. Spawn is a free verb
    # whose first argument is the parent: parenthood follows the argument,
    # not spawn order or the caller — supervision, death propagation, and
    # escalation route to that local parent automatically (INFO-014,
    # INFO-005, INFO-011). role= on the call is the lead's role message: a
    # middle agent's first turn starts with its children already active and
    # its role known.
    liaison = room(self, "liaison")       # cross-group contact: only through
                                          # what the setter wired
    leads = {
        "a": await spawn(self, Agent, requirement=..., acceptance=..., channels=[liaison]),
        "b": await spawn(self, Agent, requirement=..., acceptance=..., channels=[liaison]),
        "c": await spawn(self, Agent, requirement=..., acceptance=...),
    }                                     # "c" isolated by default
    workers = {
        w.id: await spawn(                # first arg is the parent — the
            leads[w.group], Worker,       # worker is created in the lead's
            requirement=w.req,            # position; role= is the lead's
            acceptance=w.crit,            # role message
            role=w.role,
        )
        for w in org.workers
    }

    # Extension: because verbs are free functions over plain values, agents
    # construct their own high-level abstractions outside the harness
    # release cycle (INFO-007) — e.g. a verifier factory:
    def verifier(parent, req, crit):
        return spawn(parent, Verifier, requirement=req, acceptance=crit)

    # One forced mechanic, flagged for review: children spawned inside one
    # action start their first turn only after the action settles. That is
    # what makes INFO-019's wording literal — when a lead's first turn runs,
    # its subagents are already active and its role message is in its context
    # — and it avoids the race where a lead starts before its workers exist.
    # Middle agents remain agents with their own turns; their work is
    # verification and operational support for their subtree, not
    # re-decomposition.
    org = self.publish(headline="3 groups / 5 workers, one action",
                       summary="who verifies and supports whom",
                       report=wiring_and_roles)
    return {"headline": org.headline, "artifacts": [org.id]}


# INFO-010 (re-decompose from within a child) needs no dedicated calls: a
# child discovering under-scope calls spawn(self, ...) mid-task. Turn 5 shows the
# one-shot variant (INFO-019); the values principle it leans on is the same
# one turn 1's delegation, INFO-012's artifact payloads, and the agent kinds
# use: handles, specs, and helpers are all constructed values — which is
# what makes agent-authored extension verbs compose.
