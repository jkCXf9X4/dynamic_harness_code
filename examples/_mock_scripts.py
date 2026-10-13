"""Shared mock-driver scripts for the value demo and the integration tests.

``examples/value_demo.py`` and ``tests/test_integration.py`` both drive the
same fan-out session (root publishes a plan, spawns 3 children, one child
fails, the parent awaits and aggregates). The scripts were near-verbatim
duplicates; they now live here so both consumers import one copy.

The only legitimate difference between the two consumers is the child report
*body*: the demo uses the long :data:`CHILD_REPORT` (it measures how much of
that body the parent's context never sees — progressive disclosure), while the
integration test uses a short literal. The builders below take the body as an
argument so each consumer keeps its exact bytes; everything else is shared.
"""

from __future__ import annotations

#: The long child report body. The progressive-disclosure demo measures how
#: much of this the parent's context never sees.
CHILD_REPORT = (
    "The AI agent market is projected to grow from $5.1B in 2024 to $47.1B "
    "by 2030, a compound annual growth rate of 44.5%. Enterprise adoption is "
    "driven by customer support automation, code generation, and knowledge "
    "management. The competitive landscape is consolidating around three "
    "platform vendors, with open-source alternatives capturing 22% of "
    "developer mindshare. Key risks include model hallucination in "
    "high-stakes domains, regulatory uncertainty in the EU AI Act, and "
    "compute cost volatility. Recommended posture: invest in evaluation "
    "tooling and human-in-the-loop review before broad deployment."
)

#: A child that fails: crash containment demo (INFO-005).
CHILD_FAIL = (
    "result = fail('risk data source unavailable; requirement unreachable')\n"
)


def build_child_ok(report_body: str) -> str:
    """A child that succeeds: publish an artifact, then complete.

    The report body is inlined via ``repr()`` so the block is self-contained
    (the agent's REPL namespace only holds the in-code surface, not demo
    globals).
    """
    return (
        "art = publish('child finding', 'child summary', "
        + repr(report_body)
        + ")\n"
        "result = complete('child done', artifacts=[art.id])\n"
    )


def build_root_script(child_ok: str, child_fail: str = CHILD_FAIL) -> list[str]:
    """The root's two coded actions: fan out, then aggregate and settle.

    Child code is inlined via ``repr()`` so the blocks are self-contained.
    """
    return [
        # Turn 1: publish the plan, spawn 3 children (fan-out, INFO-009).
        (
            "plan = publish('research plan', 'fan out to 3 children', "
            "{'plan': 'market research on AI agents'})\n"
            "c1 = spawn('research market size', acceptance=('done',), "
            "driver=MockDriver.single(" + repr(child_ok) + "))\n"
            "c2 = spawn('research competitors', acceptance=('done',), "
            "driver=MockDriver.single(" + repr(child_ok) + "))\n"
            "c3 = spawn('research risks', acceptance=('done',), "
            "driver=MockDriver.single(" + repr(child_fail) + "))\n"
            "result = complete('spawned 3 children', artifacts=[plan.id])\n"
        ),
        # Turn 2: await every child (ensure-terminal), aggregate the artifact
        # ids of the survivors, publish the final artifact, complete.
        (
            "ids = []\n"
            "for h in (c1, c2, c3):\n"
            "    comp = await_(h)\n"
            "    if comp.status.value == 'completed':\n"
            "        ids.extend(comp.artifact_ids)\n"
            "final = publish('final report', 'aggregated findings', "
            "{'artifact_ids': ids})\n"
            "result = complete('root done', artifacts=[final.id])\n"
        ),
    ]
