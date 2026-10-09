"""IMP-004 — token/cost accumulation at the driver seam.

The inert ``AgentNode`` usage fields get a single provenance (decision 0011):
the client records the last response's usage/cost, the driver is the ONE
write seam (``agent.record_usage``), and ``build_agent_tree`` is the ONE read
seam. These tests pin the seam: a spy client returning usage populates the
node and accumulates exactly (no double count); a usage-less call leaves the
agent zero; the mock path reports zeros; and ``agents.txt``/``stats.json``
report real values after an LLM-driven run.
"""

from __future__ import annotations

import json

from dhc.framework.agent import Agent
from dhc.ui.state import (
    StateWriter,
    build_agent_tree,
    build_stats,
    render_text_tree,
)
from dhc.data.models import AgentStatus
from dhc.llm.driver import LLMDriver, MockDriver
from dhc.llm.llm import MockLLM


class _UsageClient:
    """Fake LLM client that returns a fixed block and records usage/cost on
    itself, exactly like :class:`~dhc.llm.LLMClient` does after a provider
    call (the seam the driver reads)."""

    def __init__(self, blocks, usage, cost_usd):
        self._blocks = list(blocks)
        self._calls = 0
        self._last_usage = usage
        self._last_cost = cost_usd

    def generate_code_block(self, prompt, context):
        if self._calls >= len(self._blocks):
            return None
        code = self._blocks[self._calls]
        self._calls += 1
        return code


def _bare_agent() -> Agent:
    return Agent(id="a1", requirement="req")


# --------------------------------------------------------------------------- #
# The accumulation point on the agent
# --------------------------------------------------------------------------- #


def test_record_usage_accumulates_exactly():
    """Two calls with usage sum exactly (no double count); a None-usage call
    adds nothing."""
    agent = _bare_agent()
    agent.record_usage(
        {"prompt_tokens": 10, "completion_tokens": 5, "cached_tokens": 2}, 0.01
    )
    agent.record_usage(
        {"prompt_tokens": 7, "completion_tokens": 3, "cached_tokens": 1}, 0.02
    )
    assert agent.prompt_tokens == 17
    assert agent.completion_tokens == 8
    assert agent.cached_tokens == 3
    assert agent.tokens == 25
    assert agent.cost_usd == 0.03

    # A None-usage call contributes nothing (no crash, no fabricated number).
    agent.record_usage(None, None)
    assert agent.prompt_tokens == 17
    assert agent.completion_tokens == 8
    assert agent.cost_usd == 0.03


def test_record_usage_missing_keys_contribute_nothing():
    """A usage dict missing keys (or with None values) adds nothing for them."""
    agent = _bare_agent()
    agent.record_usage({"prompt_tokens": 4}, None)
    assert agent.prompt_tokens == 4
    assert agent.completion_tokens == 0
    assert agent.cached_tokens == 0
    assert agent.cost_usd == 0.0


# --------------------------------------------------------------------------- #
# The driver write seam
# --------------------------------------------------------------------------- #


def test_driver_writes_usage_to_agent():
    """A spy client returning usage drives LLMDriver.__call__; the agent's
    counters are non-zero and cumulative across calls."""
    agent = _bare_agent()
    client = _UsageClient(
        ["x = 1\n", "complete('done')\n"],
        usage={"prompt_tokens": 100, "completion_tokens": 20, "cached_tokens": 10},
        cost_usd=0.05,
    )
    driver = LLMDriver(client)
    assert driver(agent) == "x = 1\n"
    assert agent.prompt_tokens == 100
    assert agent.completion_tokens == 20
    assert agent.cached_tokens == 10
    assert agent.cost_usd == 0.05

    # Second call accumulates (the exact sum, not a double count).
    assert driver(agent) == "complete('done')\n"
    assert agent.prompt_tokens == 200
    assert agent.completion_tokens == 40
    assert agent.cached_tokens == 20
    assert agent.cost_usd == 0.10


def test_no_usage_leaves_agent_zero():
    """A client with no usage (None) leaves the agent's fields at zero — no
    crash, no fabricated number."""
    agent = _bare_agent()
    client = _UsageClient(["x = 1\n"], usage=None, cost_usd=None)
    driver = LLMDriver(client)
    assert driver(agent) == "x = 1\n"
    assert agent.prompt_tokens == 0
    assert agent.completion_tokens == 0
    assert agent.cached_tokens == 0
    assert agent.tokens == 0
    assert agent.cost_usd == 0.0


def test_client_without_usage_attrs_is_ignored():
    """A client that never sets _last_usage (e.g. a bare fake) is ignored by
    the seam — the driver still returns the block and the agent stays zero."""
    agent = _bare_agent()

    class _BareClient:
        def generate_code_block(self, prompt, context):
            return "x = 1\n"

    driver = LLMDriver(_BareClient())
    assert driver(agent) == "x = 1\n"
    assert agent.prompt_tokens == 0
    assert agent.cost_usd == 0.0


# --------------------------------------------------------------------------- #
# The read seam: view-model + stats
# --------------------------------------------------------------------------- #


def _runtime_with_agent(agent):
    """A minimal runtime stand-in exposing the registry + API the view-model
    reads (``_agents``, ``children_of``, ``status``)."""

    class _RT:
        def __init__(self, agent):
            self._agents = {agent.id: agent}

        def children_of(self, aid):
            return list(self._agents[aid].children)

        def status(self, aid):
            return AgentStatus.pending

    return _RT(agent)


def test_build_agent_tree_reads_accumulated_usage():
    """build_agent_tree copies the agent's accumulated usage into the node
    (the ONE read seam); build_stats aggregates it."""
    agent = _bare_agent()
    agent.record_usage(
        {"prompt_tokens": 120, "completion_tokens": 30, "cached_tokens": 12}, 0.07
    )
    rt = _runtime_with_agent(agent)

    nodes = build_agent_tree(rt)
    assert len(nodes) == 1
    node = nodes[0]
    assert node.prompt_tokens == 120
    assert node.completion_tokens == 30
    assert node.cached_tokens == 12
    assert node.tokens == 150
    assert node.cost_usd == 0.07
    assert node.cum_cost_usd == 0.07
    # The usage line now renders real figures.
    assert "in 120" in node.usage
    assert "out 30" in node.usage

    stats = build_stats(rt)
    assert stats.agents == 1
    assert stats.tokens == 150
    assert stats.prompt_tokens == 120
    assert stats.cached_tokens == 12
    assert stats.cost_usd == 0.07
    assert stats.cache_hit_rate == 12 / 120


def test_mock_path_reports_zeros():
    """The mock path (MockDriver / MockLLM) never records usage, so the
    view-model and stats report zeros and the usage line renders empty."""
    agent = _bare_agent()
    rt = _runtime_with_agent(agent)

    # MockDriver has no client and never calls record_usage.
    driver = MockDriver.single("complete('done')\n")
    assert driver(agent) == "complete('done')\n"
    assert agent.prompt_tokens == 0
    assert agent.cost_usd == 0.0

    # MockLLM leaves _last_usage None, so a driver over it writes nothing.
    mock_llm = MockLLM({"req": "x = 1\n"})
    assert mock_llm._last_usage is None
    assert mock_llm._last_cost is None
    driver2 = LLMDriver(mock_llm)
    assert driver2(agent) == "x = 1"  # MockLLM strips fences (and trailing newline)
    assert agent.prompt_tokens == 0
    assert agent.cost_usd == 0.0

    nodes = build_agent_tree(rt)
    node = nodes[0]
    assert node.tokens == 0
    assert node.prompt_tokens == 0
    assert node.completion_tokens == 0
    assert node.cached_tokens == 0
    assert node.cost_usd == 0.0
    assert node.usage == ""

    stats = build_stats(rt)
    assert stats.tokens == 0
    assert stats.prompt_tokens == 0
    assert stats.cost_usd == 0.0
    assert stats.cache_hit_rate == 0.0


# --------------------------------------------------------------------------- #
# End-to-end through the real pump: agents.txt / stats.json
# --------------------------------------------------------------------------- #


def test_agents_txt_and_stats_report_real_values(tmp_path, monkeypatch):
    """An LLM-driven run (spy client with usage) through the pump: agents.txt
    shows the token figures and stats.json shows the aggregated totals."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    from dhc.data.config import Settings
    from dhc.wiring import build_runtime

    settings = Settings(workspace_root=tmp_path, artifact_root=tmp_path)
    rt = build_runtime(mock=False, artifact_root=tmp_path, settings=settings)
    rt.start()
    try:
        driver = LLMDriver(
            _UsageClient(
                ["complete('done')\n"],
                usage={"prompt_tokens": 500, "completion_tokens": 50, "cached_tokens": 50},
                cost_usd=0.123,
            )
        )
        handle = rt.spawn("usage-e2e", driver=driver)
        completion = handle.await_()
        assert completion.status == AgentStatus.completed

        writer = StateWriter(rt, root=tmp_path / "run")
        writer.snapshot(force=True)

        agents_txt = (tmp_path / "run" / "agents.txt").read_text()
        assert "in 500" in agents_txt
        assert "out 50" in agents_txt
        assert "$0.123" in agents_txt

        stats = json.loads((tmp_path / "run" / "stats.json").read_text())
        assert stats["agents"] == 1
        assert stats["tokens"] == 550
        assert stats["prompt_tokens"] == 500
        assert stats["cached_tokens"] == 50
        assert stats["cost_usd"] == 0.123
    finally:
        rt.stop()


def test_mock_run_reports_zero_in_files(tmp_path):
    """The mock path through the pump: agents.txt has no usage figures and
    stats.json reports zero tokens/cost (not a crash, not a fabricated number)."""
    from dhc.data.config import Settings
    from dhc.wiring import build_runtime

    settings = Settings(workspace_root=tmp_path, artifact_root=tmp_path)
    rt = build_runtime(mock=True, artifact_root=tmp_path, settings=settings)
    rt.start()
    try:
        handle = rt.spawn("mock-e2e")
        completion = handle.await_()
        assert completion.status == AgentStatus.completed

        writer = StateWriter(rt, root=tmp_path / "run")
        writer.snapshot(force=True)

        agents_txt = (tmp_path / "run" / "agents.txt").read_text()
        assert "in " not in agents_txt
        assert "$" not in agents_txt

        stats = json.loads((tmp_path / "run" / "stats.json").read_text())
        assert stats["agents"] == 1
        assert stats["tokens"] == 0
        assert stats["prompt_tokens"] == 0
        assert stats["cost_usd"] == 0.0
    finally:
        rt.stop()
