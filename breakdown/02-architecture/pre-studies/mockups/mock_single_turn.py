"""INFO-002 · INFO-003 — one turn is one self-verifying Python block.

One expressive block replaces N tool-call turns: the runtime persists this
block, executes it against the agent's persistent REPL, and returns a summary
plus artifact IDs. This block is the whole action space — loops, transforms,
verification, and error handling all happen here.
"""

from __future__ import annotations

from _support import Agent, Result, ToolOutput, bash


def turn(agent: Agent, task: str = "hello_turn.py") -> Result:
    # -- analyze ----------------------------------------------------------
    # Restate the allocation so the verify leg has teeth (the small V).
    requirement = agent.requirement
    acceptance = tuple(agent.acceptance)

    # -- implement --------------------------------------------------------
    # A tool is just a callable the agent invokes; the output is one object.
    out: ToolOutput = agent.tool(bash, f"pytest -q {task}")

    # Search where search is cheap, read the tail where it is not.
    failures = out.search("FAILED")
    tail = out.read(size=4_000, offset=0)  # size-capped tail read

    # -- verify against the parent's acceptance ---------------------------
    if failures:
        return agent.fail(
            f"{requirement}: {len(failures)} failure(s) — {failures[0]!r}")

    missing = [a for a in acceptance if a not in out.text]
    if missing:
        return agent.fail(f"acceptance signal(s) missing from output: {missing}")

    # -- report -----------------------------------------------------------
    # A summary plus artifact IDs go back to the parent; detail stays behind
    # the artifact (headline → summary → report, pulled on demand).
    report = agent.publish(
        headline=f"{task} passes its acceptance",
        summary=f"{len(out.text.splitlines())} lines, {len(failures)} failures",
        report=tail,
    )
    return agent.complete(f"{task} verified", artifacts=(report,))


if __name__ == "__main__":
    a = Agent(requirement="run the hello_turn suite", acceptance=("passed",))
    print(turn(a))