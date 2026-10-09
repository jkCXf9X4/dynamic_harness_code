"""Tests pinning the H-06 checkpoint split (decision 0012).

Two checkpoint mechanisms coexist, and the split is a deliberate control
split, not a vision violation:

* **Workspace checkpoints** — ``state["checkpoints"]`` in the fabrication kit
  (``src/dhc/llm/fabrication.py``). Agent-owned, in-memory, ordinary data the
  agent reads and writes. This is the agent's side of the control split, and
  it is what the vision's A3 surface ("context and history as ordinary data")
  promises.
* **On-disk ``CheckpointStore``** — ``src/dhc/agent/checkpoint.py``, surfaced
  to the operator via ``/resume`` in the terminal. Operator-only, durable,
  out-of-process. This is the operator's side of the control split.

These tests pin that split so it cannot silently drift:

* the production runtime never instantiates the on-disk store (operator-only,
  dormant in production);
* the terminal's ``/resume`` reads the operator's ``runtime.checkpoint_store``
  (the operator's side), and finds nothing when the store is absent — it never
  falls back to the agent's workspace checkpoints;
* the agent's workspace ``checkpoint`` citizen writes only to
  ``state["checkpoints"]`` and never to the on-disk store (the two mechanisms
  are independent).
"""

import threading
from pathlib import Path

from dhc.agent.agent import Agent, AgentHandle
from dhc.agent.checkpoint import AgentCheckpoint, CheckpointStore
from dhc.llm.fabrication import fabrication_kit
from dhc.ui.terminal import Terminal
from dhc.wiring import build_runtime


def _register_agent(rt, agent_id="a1", requirement="r"):
    """Register an agent on the runtime WITHOUT starting a worker thread.

    Same bookkeeping as ``Runtime.spawn`` minus the thread, so the workspace
    checkpoint citizen can be driven directly (mirrors test_fabrication.py).
    """
    agent = Agent(
        id=agent_id,
        requirement=requirement,
        runtime=rt,
    )
    rt._agents[agent_id] = agent
    rt._handles[agent_id] = AgentHandle(agent_id, rt)
    rt._stop_flags[agent_id] = threading.Event()
    return agent


def _wired(tmp_path):
    rt = build_runtime(mock=True, artifact_root=str(tmp_path))
    rt.start()
    return rt


# --------------------------------------------------------------------------- #
# The on-disk store is operator-only: never instantiated in production
# --------------------------------------------------------------------------- #


def test_production_runtime_has_no_on_disk_checkpoint_store(tmp_path):
    """The on-disk ``CheckpointStore`` is the operator's resumability
    mechanism, not a live production mechanism: ``build_runtime`` never
    instantiates it, so the runtime carries no ``checkpoint_store``.

    This is the crux of the H-06 split — the on-disk store is dormant in
    production, which is why the agent cannot (and should not) read it.
    """
    rt = _wired(tmp_path)
    try:
        assert getattr(rt, "checkpoint_store", None) is None
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# The terminal /resume reads the operator's store, not the workspace
# --------------------------------------------------------------------------- #


def test_terminal_resume_reads_operator_store(tmp_path):
    """The terminal's ``/resume`` handler reads the operator's on-disk
    ``runtime.checkpoint_store``. With no store (the production case) it finds
    nothing; when the operator attaches a store, it reads from it. It never
    falls back to the agent's workspace checkpoints.
    """
    rt = _wired(tmp_path)
    try:
        term = Terminal(runtime=rt)

        # Production: no on-disk store -> /resume finds nothing.
        assert term._checkpoint("a1") is None

        # The operator attaches the on-disk store -> /resume reads it.
        store = CheckpointStore(tmp_path / "checkpoints")
        store.save(AgentCheckpoint(agent_id="a1", turn_counter=3))
        rt.checkpoint_store = store
        cp = term._checkpoint("a1")
        assert cp is not None
        assert cp.agent_id == "a1"
        assert cp.turn_counter == 3
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# The agent's workspace checkpoint is independent of the on-disk store
# --------------------------------------------------------------------------- #


def test_workspace_checkpoint_is_independent_of_on_disk_store(tmp_path):
    """The agent's workspace ``checkpoint`` citizen writes only to
    ``state["checkpoints"]`` (its own ordinary data) and never to the on-disk
    store. The two mechanisms are independent: using the agent's checkpoint
    does not create or touch the operator's on-disk store.
    """
    rt = _wired(tmp_path)
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        engine.inject(agent.id, {"x": 1})

        # The agent's workspace checkpoint writes to state["checkpoints"].
        idx = kit["checkpoint"]("milestone", done=("step1",))
        assert idx == 0
        assert "checkpoints" in kit["state"]
        assert kit["state"]["checkpoints"][0]["note"] == "milestone"

        # It never touches the on-disk store: the production runtime has no
        # checkpoint_store, and the workspace checkpoint does not create one.
        assert getattr(rt, "checkpoint_store", None) is None
    finally:
        rt.stop()
