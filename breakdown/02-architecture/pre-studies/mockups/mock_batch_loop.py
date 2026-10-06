"""INFO-001 · INFO-002 — one expressive block replaces N tool-call turns.

The loop, the transform, and the selective failure handling all live inside a
single action. Nothing here is a tool-call turn — the code block is the action
space, so the agent gets a full Python loop instead of N round-trips.
"""

from __future__ import annotations

from _support import Agent, Result, ToolOutput


def _run(item: str) -> str:
    """A stand-in tool that passes for clean items and fails for the rest."""
    if item == "turn_goodbye":
        return (f"================= {item} =================\n"
                "1 failed in 0.02s\nFAILED breaking change in turn_goodbye")
    return (f"================= {item} =================\n"
            "1 passed in 0.02s\nwarnings summary:\n"
            f"hello_turn.py::{item}\n  1 warning in 0.31s\n")


def turn(agent: Agent, items: tuple[str, ...] = ("turn_hello", "turn_goodbye")) -> Result:
    passed, failed = [], []

    for item in items:
        out: ToolOutput = agent.tool(_run, item)

        if out.search("FAILED"):
            # Selective failure handling without leaving the block.
            tail = out.read(size=2_000, offset=0).splitlines()[-1]
            failed.append((item, tail))
            continue

        missing = [a for a in agent.acceptance if a not in out.text]
        if missing:
            failed.append((item, f"missing: {missing}"))
            continue
        passed.append(item)

    if failed:
        report = agent.publish("batch run failures",
                               f"{len(failed)}/{len(items)} items failed", failed)
        return agent.fail(f"{len(failed)} item(s) failed; detail at {report.id}")

    report = agent.publish("batch run clean",
                           f"{len(passed)} items matched acceptance", passed)
    return agent.complete(f"batch verified: {len(passed)}/{len(items)}", artifacts=(report,))


if __name__ == "__main__":
    a = Agent(requirement="verify the whole batch", acceptance=("passed",))
    print(turn(a))