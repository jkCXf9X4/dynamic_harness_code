"""INFO-004 · INFO-030 · INFO-045 — decomposition by writing delegation code.

A parent decomposes work by writing code: nothing here is a fixed tool call.
Each child is spawned with encapsulated context — its allocated requirement
plus the acceptance it must meet; nothing more is visible. The parent registers
a completion callback at spawn time, by the held spawn handle, and settled
values arrive as *data* between the parent's own actions. No stream is ever
drained or polled from agent code.

Sketch convention: module globals stand in for REPL variables, and the
`handle_child_done` call stands in for the runtime delivering a settled child
event between the parent's actions. The child body is sketched so the
delegation interface reads end-to-end.
"""

from __future__ import annotations

from _support import Agent, Event, Result, ToolOutput, bash

# Parent REPL: the handles it spawned and the values delivered since.
_spawned: list[Agent] = []
_settled: dict[str, Result] = {}


def handle_child_done(event: Event) -> None:
    """Callback shape the runtime invokes between the parent's own actions."""
    child, result = event.originating_agent, event.result
    assert child is not None and result is not None
    # Delivery is by held handle only — no stream surface is reachable here.
    if child.id not in {c.id for c in _spawned}:
        return
    _settled[child.id] = result


def child_turn(child: Agent, file: str) -> Result:
    """The spawned child's own coded action — a small V in its own REPL."""
    out: ToolOutput = child.tool(bash, f"pytest -q {file}")
    if out.search("FAILED"):
        return child.fail(f"{file} failed acceptance")
    report = child.publish(headline=f"{file} done", summary="vertex computed",
                           report=out.text)
    return child.complete(f"{file} verified", artifacts=(report,))


def turn(agent: Agent, files: tuple[str, ...] = ("a_slice.py", "b_slice.py")) -> Result:
    # -- parent action 1: delegate ---------------------------------------
    # Context in: each child sees only its requirement and acceptance.
    for f in files:
        child = agent.spawn(requirement=f"compute and verify {f}",
                            acceptance=("passed",),
                            on_done=handle_child_done)  # registration by held handle
        _spawned.append(child)
    # The parent's own action is done; deliveries happen between actions.

    # -- runtime simulation, standing in for the next few turns -----------
    # Each child's block runs in its own REPL; the runtime delivers an Event
    # carrying the settled result back to the parent's callback.
    for child, f in zip(_spawned, files):
        result = child_turn(child, f)
        handle_child_done(Event(done=True, ok=result.ok, value=result.value,
                                reason=result.reason, artifacts=result.artifacts,
                                originating_agent=child, result=result))

    # -- parent action 3: report ------------------------------------------
    # Every handle settled → pull detail on demand via artifacts, then close.
    pending = [c.id for c in _spawned if c.id not in _settled]
    if pending:
        return agent.fail(f"still waiting on {len(pending)} child handle(s)")

    rows = [(c.id[:8], _settled[c.id].ok, _settled[c.id].value) for c in _spawned]
    report = agent.publish("fan-out summary",
                           f"{len(_settled)}/{len(_spawned)} children settled", rows)
    return agent.complete("all child results collected", artifacts=(report,))


if __name__ == "__main__":
    a = Agent(requirement="verify both slices via children", acceptance=("passed",))
    print(turn(a))