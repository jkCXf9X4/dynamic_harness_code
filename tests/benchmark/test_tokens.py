"""Token accounting end to end: driver usage → run metrics → aggregate → baseline.

The vision bet ("one code block per turn beats tool-call turns on cost per
resolved task") is measured in *tokens*: the benchmarked provider exposes no
usable price, so ``cost_usd`` stays 0.0 and is unmeasured, never estimated.

These tests pin:

* usage flowing from a driver/client seam (``Agent.record_usage``) into
  :class:`RunMetrics`, summed across the mesh, through ``run_benchmark``;
* the difference between a measured zero and "no usage recorded";
* the token aggregate and its baseline comparison, without any currency.
"""

from __future__ import annotations

import json

import pytest

from dhc.benchmark import (
    baseline_from_runs,
    compare_to_baseline,
    load_baseline,
    run_benchmark,
    save_baseline,
    summarize_tokens,
)
from dhc.benchmark.baseline import BaselineError
from dhc.benchmark.metrics import collect_metrics
from dhc.benchmark.tasks import FibonacciTask
from dhc.llm.driver import LLMDriver, MockDriver
from dhc.llm.llm import MockLLM

SOLVE = (
    "with open('fib.txt', 'w') as f:\n"
    "    f.write('55')\n"
    "complete('wrote fib.txt')"
)


class UsageClient:
    """Fake LLM client with the usage seam ``LLMClient`` exposes.

    ``generate_code_block`` records ``_last_usage``/``_last_cost`` on itself,
    exactly like the real client does after a provider call; the driver reads
    them and writes them onto the agent via ``record_usage``.
    """

    def __init__(self, blocks, usage, cost_usd=None):
        self._blocks = list(blocks)
        self._calls = 0
        self._usage = usage
        self._cost = cost_usd
        # Parity with LLMClient: nothing recorded before the first call.
        self._last_usage = None
        self._last_cost = None

    def generate_code_block(self, prompt, context=None):
        if self._calls >= len(self._blocks):
            return None
        code = self._blocks[self._calls]
        self._calls += 1
        self._last_usage = self._usage
        self._last_cost = self._cost
        return code


def _driver_factory(usage, cost_usd=None, blocks=None):
    """A per-task driver over a usage-reporting fake client."""
    return lambda task: LLMDriver(UsageClient(blocks or [SOLVE], usage, cost_usd))


def _run(tmp_path, **kwargs):
    return run_benchmark(
        tasks=[FibonacciTask()],
        prompts={"seed": "{task}"},
        results_dir=tmp_path / "results",
        mock=True,  # runtime in mock mode; driver_factory overrides the driver
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# Usage flows end to end
# --------------------------------------------------------------------------- #


def test_usage_flows_from_driver_into_run_metrics(tmp_path):
    runs = _run(
        tmp_path,
        driver_factory=_driver_factory(
            {"prompt_tokens": 900, "completion_tokens": 100, "cached_tokens": 40}
        ),
    )
    m = runs[0]
    assert m.correct is True and m.passed is True
    assert m.usage_recorded is True
    assert m.prompt_tokens == 900
    assert m.completion_tokens == 100
    assert m.cached_tokens == 40
    assert m.total_tokens == 1000
    assert m.tokens_per_resolved_task == 1000.0
    # Cost is unmeasured for this provider, never estimated.
    assert m.cost_usd == 0.0
    assert m.extra["cost_usd_measured"] is False


def test_run_metrics_equal_the_mesh_usage_sum(tmp_path):
    """The run's token figures are the aggregate over every agent, once each."""
    from dhc.wiring import build_runtime

    seen = []

    def factory():
        rt = build_runtime(mock=True)
        seen.append(rt)
        return rt

    runs = run_benchmark(
        tasks=[FibonacciTask()],
        prompts={"seed": "{task}"},
        runtime_factory=factory,
        results_dir=tmp_path / "results",
        mock=True,
        driver_factory=_driver_factory({"prompt_tokens": 10, "completion_tokens": 5}),
    )
    m = runs[0]
    rt = seen[0]
    expected_prompt = sum(a.prompt_tokens for a in rt._agents.values())
    expected_completion = sum(a.completion_tokens for a in rt._agents.values())
    assert m.prompt_tokens == expected_prompt == 10
    assert m.completion_tokens == expected_completion == 5
    assert m.total_tokens == 15


def test_aggregate_usage_sums_every_agent_in_the_mesh():
    """Root + delegated child both report usage; the run total is their sum."""
    from dhc.benchmark.run import _aggregate_usage
    from dhc.framework.agent import Agent
    from dhc.wiring import build_runtime

    root = Agent(id="root", requirement="root req")
    child = Agent(id="child", requirement="child req", parent_id="root")
    root.record_usage({"prompt_tokens": 10, "completion_tokens": 5}, None)
    child.record_usage(
        {"prompt_tokens": 7, "completion_tokens": 3, "cached_tokens": 2}, None
    )

    rt = build_runtime(mock=True)
    rt._agents = {"root": root, "child": child}
    assert _aggregate_usage(rt) == {
        "prompt_tokens": 17,
        "completion_tokens": 8,
        "cached_tokens": 2,
    }


def test_zero_usage_run_differs_from_not_recorded(tmp_path):
    """A provider that reports zero tokens is measured; mock mode is not."""
    zero = _run(
        tmp_path / "zero",
        driver_factory=_driver_factory({"prompt_tokens": 0, "completion_tokens": 0}),
    )[0]
    assert zero.usage_recorded is True
    assert zero.total_tokens == 0
    assert zero.tokens_per_resolved_task == 0.0  # measured zero, resolved

    not_recorded = run_benchmark(
        tasks=[FibonacciTask()],
        prompts={"seed": "{task}"},
        results_dir=tmp_path / "mock",
        mock=True,  # MockDriver never calls record_usage
    )[0]
    assert not_recorded.usage_recorded is False
    assert not_recorded.total_tokens == 0
    assert not_recorded.tokens_per_resolved_task is None  # unknown, not free

    llm_without_usage = _run(
        tmp_path / "nousage",
        driver_factory=lambda task: LLMDriver(MockLLM(default=SOLVE)),
    )[0]
    assert llm_without_usage.usage_recorded is False


def test_mock_driver_never_records_usage():
    """The documented seam invariant the ``usage_recorded`` flag relies on."""
    from dhc.framework.agent import Agent

    agent = Agent(id="a1", requirement="req")
    driver = MockDriver.single(SOLVE)
    assert driver(agent) == SOLVE
    assert agent.prompt_tokens == 0
    assert agent.completion_tokens == 0
    assert agent.cost_usd == 0.0


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def _metrics(*, passed=True, recorded=True, tokens=1000, prompt=None):
    prompt = tokens if prompt is None else min(prompt, tokens)
    return collect_metrics(
        prompt_id="p",
        task_id="t",
        status="completed" if passed else "failed",
        correct=True if passed else False,
        total_tokens=tokens,
        prompt_tokens=prompt,
        completion_tokens=tokens - prompt,
        usage_recorded=recorded,
    )


def test_summary_divides_by_resolved_recorded_runs_only():
    runs = [
        _metrics(passed=True, recorded=True, tokens=1000),
        _metrics(passed=True, recorded=False, tokens=0),
        _metrics(passed=False, recorded=True, tokens=600),
    ]
    s = summarize_tokens(runs)
    assert (s.runs, s.recorded_runs) == (3, 2)
    assert (s.resolved_runs, s.resolved_recorded_runs) == (2, 1)
    assert s.total_tokens == 1600
    # All measured tokens (including the failed attempt) over the resolved
    # runs that were actually measured; the unmeasured pass is not a zero.
    assert s.tokens_per_resolved_task == 1600.0
    assert s.complete is False


def test_summary_without_recorded_usage_is_not_a_zero():
    s = summarize_tokens([_metrics(passed=True, recorded=False, tokens=0)])
    assert s.tokens_per_resolved_task is None
    assert s.to_dict()["tokens_per_resolved_task"] is None
    assert s.to_dict()["cost_usd"] is None  # unmeasured, not free


# --------------------------------------------------------------------------- #
# Baseline comparison (tokens, never currency)
# --------------------------------------------------------------------------- #


def test_baseline_roundtrip_and_comparison(tmp_path):
    reference = [_metrics(passed=True, recorded=True, tokens=1000)]
    baseline = baseline_from_runs("tool-call-path", reference, notes="reference set")
    assert baseline.tokens_per_resolved_task == 1000.0

    path = save_baseline(baseline, tmp_path / "baseline.json")
    loaded = load_baseline(path)
    assert loaded == baseline
    assert json.loads(path.read_text())["tokens_per_resolved_task"] == 1000.0

    cheaper = compare_to_baseline(
        [_metrics(passed=True, recorded=True, tokens=800)], loaded
    )
    assert cheaper.comparable is True
    assert cheaper.current_tokens_per_resolved_task == 800.0
    assert cheaper.ratio == pytest.approx(0.8)
    assert cheaper.delta == pytest.approx(-200.0)
    assert "ratio 0.800" in cheaper.format_line()

    # Unrecorded usage cannot be compared — not treated as zero tokens.
    unknown = compare_to_baseline([_metrics(passed=True, recorded=False)], loaded)
    assert unknown.comparable is False
    assert unknown.ratio is None
    assert "not comparable" in unknown.format_line()

    # A run set that resolved nothing has no per-task figure either.
    unresolved = compare_to_baseline([_metrics(passed=False, tokens=1000)], loaded)
    assert unresolved.comparable is False


def test_baseline_rejects_unmeasured_or_unresolved_sets(tmp_path):
    with pytest.raises(BaselineError):
        baseline_from_runs("none", [_metrics(recorded=False)])
    with pytest.raises(BaselineError):
        baseline_from_runs("unresolved", [_metrics(passed=False, tokens=1000)])
    with pytest.raises(BaselineError):
        load_baseline(tmp_path / "missing.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(BaselineError):
        load_baseline(bad)
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"label": "x", "total_tokens": 10, "resolved_tasks": 0}))
    with pytest.raises(BaselineError):
        load_baseline(empty)


def test_baseline_compare_through_run_benchmark(tmp_path):
    """A real run set records the reference and compares against it."""
    results = tmp_path / "results"
    baseline_path = tmp_path / "baseline.json"
    runs = run_benchmark(
        tasks=[FibonacciTask()],
        prompts={"seed": "{task}"},
        results_dir=results,
        mock=True,
        driver_factory=_driver_factory({"prompt_tokens": 200, "completion_tokens": 50}),
        save_baseline_to=baseline_path,
        baseline_label="seed",
    )
    assert runs[0].usage_recorded is True
    assert load_baseline(baseline_path).tokens_per_resolved_task == 250.0

    # Same run set compared against its own stored baseline.
    run_benchmark(
        tasks=[FibonacciTask()],
        prompts={"seed": "{task}"},
        results_dir=tmp_path / "results2",
        mock=True,
        driver_factory=_driver_factory({"prompt_tokens": 200, "completion_tokens": 50}),
        baseline=baseline_path,
    )
    summary = json.loads((tmp_path / "results2" / "summary.json").read_text())
    assert summary["tokens_per_resolved_task"] == 250.0
    assert summary["recorded_runs"] == 1
    comparison = summary["baseline_comparison"]
    assert comparison["comparable"] is True
    assert comparison["ratio"] == pytest.approx(1.0)
    assert comparison["baseline"]["label"] == "seed"

    md = (tmp_path / "results2" / "metrics.md").read_text()
    assert "Tokens per resolved task" in md
    assert "not measured" in md  # cost is documented unavailable
    assert "250.0" in md


def test_results_json_reports_usage_provenance(tmp_path):
    results = tmp_path / "results"
    run_benchmark(
        tasks=[FibonacciTask()],
        prompts={"seed": "{task}"},
        results_dir=results,
        mock=True,  # unrecorded
    )
    data = json.loads((results / "metrics.json").read_text())
    assert data[0]["usage_recorded"] is False
    assert data[0]["tokens_per_resolved_task"] is None
    assert "n/a" in (results / "metrics.md").read_text()
