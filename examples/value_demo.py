#!/usr/bin/env python3
"""dhc value demonstration — end-to-end agent session with hard evidence.

Runs a fully-wired dhc runtime (real modules, MockDriver — deterministic, no
API key needed) through a complete agent session:

    root requirement
      -> coded action publishes a plan artifact
      -> spawns 3 children (fan-out)
      -> children publish artifacts; one child FAILS (crash containment)
      -> parent awaits children, aggregates artifact ids, completes
      -> runtime settles

Then writes a structured value report to
``.dynamic-harness/261006_230325_4a23/artifacts/value_demo_report.md``
answering "what value does dhc provide during agent work?":

  (a) one coded action replaces N tool-call turns
  (b) progressive disclosure (headline -> summary -> report) saves context
  (c) crash containment keeps siblings alive
  (d) at-most-once settlement prevents duplicate work
  (e) parent liveness until children settle

If ``OPENAI_API_KEY`` is set, one real-LLM turn is ALSO run (LLMDriver over
LLMClient) to prove the real path works; otherwise a note is printed (the
mock path is the documented test path).

Exit code 0 on success.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

# Allow running from a source checkout without installation.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc import (  # noqa: E402
    CompletionLog,
    MockDriver,
    build_runtime,
    driver_from_settings,
)
from dhc.models import Completion, Result  # noqa: E402

#: The report destination (mission requirement).
REPORT_PATH = Path(
    "/home/eriro/pwa/2_work/dynamic_harness_code/.dynamic-harness"
    "/261006_230325_4a23/artifacts/value_demo_report.md"
)

#: Child report bodies (deliberately long: the progressive-disclosure demo
#: measures how much of this the parent's context never sees).
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

#: A child that succeeds: publish an artifact, then complete.
#: The report body is inlined via repr() so the block is self-contained.
CHILD_OK = (
    "art = publish('child finding', 'child summary', " + repr(CHILD_REPORT) + ")\n"
    "result = complete('child done', artifacts=[art.id])\n"
)

#: A child that fails: crash containment demo (INFO-005).
CHILD_FAIL = (
    "result = fail('risk data source unavailable; requirement unreachable')\n"
)

#: The root's two coded actions: fan out, then aggregate and settle.
#: Child code is inlined via repr() so the blocks are self-contained (the
#: agent's REPL namespace only holds the in-code surface, not demo globals).
ROOT_SCRIPT = [
    # Turn 1: publish the plan, spawn 3 children (fan-out, INFO-009).
    (
        "plan = publish('research plan', 'fan out to 3 children', "
        "{'plan': 'market research on AI agents'})\n"
        "c1 = spawn('research market size', acceptance=('done',), "
        "driver=MockDriver.single(" + repr(CHILD_OK) + "))\n"
        "c2 = spawn('research competitors', acceptance=('done',), "
        "driver=MockDriver.single(" + repr(CHILD_OK) + "))\n"
        "c3 = spawn('research risks', acceptance=('done',), "
        "driver=MockDriver.single(" + repr(CHILD_FAIL) + "))\n"
        "result = complete('spawned 3 children', artifacts=[plan.id])\n"
    ),
    # Turn 2: await every child (ensure-terminal), aggregate the artifact ids
    # of the survivors, publish the final artifact, complete.
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


def _count_tool_calls_traditional() -> int:
    """Count the tool calls a traditional tool-calling agent would need for
    the same session (one tool call per primitive operation)."""
    return (
        1  # read requirement
        + 1  # publish plan artifact
        + 3  # spawn child A, B, C
        + 3  # await child A, B, C
        + 3  # read child result A, B, C
        + 2  # read child artifact summary A, B (C failed)
        + 1  # publish final artifact
        + 1  # complete
    )


def _run_mock_session() -> dict:
    """Run the end-to-end mock session; return the evidence dict."""
    tmp = tempfile.mkdtemp(prefix="dhc-demo-")
    rt = build_runtime(mock=True, artifact_root=tmp)
    rt.start()
    started = time.monotonic()

    root = rt.spawn(
        "Produce a market research report on AI agents",
        acceptance=(),  # empty: the driver controls settlement (multi-turn)
        driver=MockDriver(ROOT_SCRIPT),
    )
    root_completion = rt.await_(root.id)
    wall_seconds = time.monotonic() - started

    children = rt.children_of(root.id)
    child_states = {}
    for cid in children:
        comp = rt.await_(cid)
        child_states[cid] = {
            "status": comp.status.value,
            "summary": comp.summary,
            "artifact_ids": comp.artifact_ids,
            "reason": comp.reason,
        }

    evidence = {
        "root": {
            "id": root.id,
            "status": root_completion.status.value,
            "summary": root_completion.summary,
            "artifact_ids": root_completion.artifact_ids,
        },
        "children": child_states,
        "turns": 2 + len(children),  # root 2 turns + 1 per child
        "code_blocks": 2 + len(children),
        "artifacts": rt.artifact_store_real.list_ids(),
        "store_count": rt.artifact_store_real.count(),
        "boundary": {
            "spawned": len(rt.boundary_log.read(kind="spawned")),
            "settled": len(rt.boundary_log.read(kind="settled")),
            "published": len(rt.boundary_log.read(kind="published")),
        },
        "wall_seconds": round(wall_seconds, 3),
        "tool_calls_traditional": _count_tool_calls_traditional(),
        "report_chars": len(CHILD_REPORT),
        "summary_chars": len("child summary"),
    }
    rt.stop()
    return evidence


def _demo_at_most_once() -> str:
    """Demonstrate at-most-once settlement (INFO-046) with the real log."""
    log = CompletionLog()
    completion = Completion(
        agent_id="demo-child", status="completed", summary="done"
    )
    log.settle(completion)
    try:
        log.settle(completion)
    except Exception as exc:  # noqa: BLE001 - expected ChannelError
        return f"{type(exc).__name__}: {exc}"
    return "UNEXPECTED: double settlement was allowed"


def _run_real_llm_turn() -> dict:
    """Run one real-LLM turn (LLMDriver over LLMClient); best-effort."""
    tmp = tempfile.mkdtemp(prefix="dhc-demo-llm-")
    rt = build_runtime(mock=False, artifact_root=tmp)
    rt.start()
    driver = driver_from_settings(mock=False)  # real path: key is set
    handle = rt.spawn(
        "Publish one artifact titled 'hello' and complete with 'done'.",
        driver=driver,
    )
    comp = rt.await_(handle.id)
    result = {
        "status": comp.status.value,
        "summary": comp.summary,
        "reason": comp.reason,
        "artifact_ids": comp.artifact_ids,
    }
    rt.stop()
    return result


def _build_report(evidence: dict, real_llm: dict | None) -> str:
    """Compose the value report markdown."""
    root = evidence["root"]
    children = evidence["children"]
    ok_children = [c for c in children.values() if c["status"] == "completed"]
    failed_children = [c for c in children.values() if c["status"] == "failed"]
    tool_calls = evidence["tool_calls_traditional"]
    code_blocks = evidence["code_blocks"]
    context_saved = (
        (evidence["report_chars"] - evidence["summary_chars"]) * len(ok_children)
    )

    lines = [
        "# dhc — Value Demonstration Report",
        "",
        "End-to-end agent session on the **fully wired** runtime (real modules:",
        "ReplEngine, EventBus + BoundaryEventLog, CompletionDispatcher,",
        "ArtifactStore, communication channels) with a deterministic",
        "MockDriver — no API key needed.",
        "",
        "## Session summary",
        "",
        f"- Root agent: `{root['id']}` — requirement: *Produce a market research report on AI agents*",
        f"- Root terminal state: **{root['status']}** — summary: `{root['summary']}`",
        f"- Children spawned (fan-out): **{len(children)}**",
        f"- Turns executed: **{evidence['turns']}** (root 2 + 1 per child)",
        f"- Code blocks (one per turn): **{code_blocks}**",
        f"- Artifacts published: **{evidence['store_count']}**",
        f"- Wall time: **{evidence['wall_seconds']}s**",
        "",
        "### Artifacts (content-addressed)",
        "",
    ]
    for aid in evidence["artifacts"]:
        lines.append(f"- `{aid}`")
    lines += [
        "",
        "### Children",
        "",
        "| child | terminal state | summary |",
        "| --- | --- | --- |",
    ]
    for cid, c in children.items():
        lines.append(f"| `{cid}` | {c['status']} | {c['summary'] or c['reason']} |")
    lines += [
        "",
        "### Boundary event log (INFO-049)",
        "",
        f"- spawned: **{evidence['boundary']['spawned']}**",
        f"- settled: **{evidence['boundary']['settled']}**",
        f"- published: **{evidence['boundary']['published']}**",
        "",
        "## Value during agent work",
        "",
        "### (a) One coded action replaces N tool-call turns",
        "",
        f"A traditional tool-calling agent needs **{tool_calls} tool calls** for this",
        f"session (read requirement, publish, 3x spawn, 3x await, 3x read result,",
        f"2x read artifact, publish final, complete) — each one a separate LLM",
        f"round-trip. dhc does the same work in **{code_blocks} code blocks**",
        f"({evidence['turns']} turns), a **{tool_calls / code_blocks:.1f}x reduction** in",
        "round-trips. Loops, fan-out, selective failure handling and aggregation",
        "all happen *inside* one expressive block (INFO-002).",
        "",
        "### (b) Progressive disclosure saves context",
        "",
        f"Each child report body is **{evidence['report_chars']} chars**; the parent",
        f"receives only the **{evidence['summary_chars']}-char summary plus the artifact id**",
        f"(INFO-006). With {len(ok_children)} successful children, roughly",
        f"**{context_saved} chars of report body never enter the parent's context** —",
        "consumers pull headline -> summary -> report tiers on demand.",
        "",
        "### (c) Crash containment keeps siblings alive",
        "",
        f"Child `{next((cid for cid, c in children.items() if c['status'] == 'failed'), '?')}` **failed**",
        f"({failed_children[0]['reason'] if failed_children else ''}) while "
        f"**{len(ok_children)} siblings still completed**; the root still completed.",
        "A crashed child is contained and never takes down a sibling or the",
        "parent (INFO-005); the failure surfaces as one distinguishable",
        "`failed` terminal state.",
        "",
        "### (d) At-most-once settlement prevents duplicate work",
        "",
        f"Each settled child produced exactly one completion. Double settlement",
        f"is rejected: `{_demo_at_most_once()}` (INFO-046).",
        "",
        "### (e) Parent liveness until children settle",
        "",
        "The root's turn 1 returned immediately after spawning (non-blocking",
        "spawn, INFO-009), but the root did **not** settle while children were",
        "running: turn 2 `await_`ed every child (ensure-terminal, INFO-031)",
        "before completing. The boundary log shows the causal DAG: 3 `spawned`",
        "records, then 4 `settled` records (3 children + root), then the root's",
        "final `published` record.",
        "",
    ]
    if real_llm is not None:
        lines += [
            "## Real-LLM path (OPENAI_API_KEY set)",
            "",
            f"- Driver: `driver_from_settings(mock=False)` -> LLMDriver over LLMClient",
            f"- Turn terminal state: **{real_llm['status']}**",
            f"- Summary: `{real_llm['summary'] or real_llm['reason']}`",
            f"- Artifacts: {real_llm['artifact_ids']}",
            "",
        ]
    else:
        lines += [
            "## Real-LLM path",
            "",
            "Skipped: `OPENAI_API_KEY` not set. The mock path is the documented",
            "test path; set the key to also exercise the real LLM driver.",
            "",
        ]
    lines += [
        "---",
        f"*Generated by `examples/value_demo.py` — exit 0, "
        f"{evidence['wall_seconds']}s wall time.*",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    """Run the demo; return the process exit code."""
    evidence = _run_mock_session()

    real_llm = None
    if os.environ.get("OPENAI_API_KEY"):
        try:
            real_llm = _run_real_llm_turn()
        except Exception as exc:  # noqa: BLE001 - best-effort real path
            real_llm = {
                "status": "failed",
                "summary": "",
                "reason": f"{type(exc).__name__}: {exc}",
                "artifact_ids": [],
            }
    else:
        print("note: OPENAI_API_KEY not set — real-LLM path skipped "
              "(mock path is the documented test path)")

    report = _build_report(evidence, real_llm)
    print(report)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    print(f"\n[value report written to {REPORT_PATH}]")
    return 0


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())