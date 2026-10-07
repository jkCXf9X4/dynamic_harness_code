"""Tests for the dhc benchmark package.

Uses tmp_path only — never writes into the repo. Exercises the failable
verifiers, the runner with a MockDriver, metrics.passed logic, scoring
correctness dominance, JSON+MD results, and the fresh-Runtime-per-run
guarantee.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dhc.benchmark import ALL_TASKS, BenchmarkTask, RunMetrics, ScoringWeights, run_benchmark, score
from dhc.benchmark.metrics import collect_metrics
from dhc.benchmark.run import _task_script, stage_workspace
from dhc.benchmark.tasks import FibonacciTask, LargestFilesTask, SynthesisTask, find_task


# --------------------------------------------------------------------------- #
# Verifiers are falsifiable
# --------------------------------------------------------------------------- #


def _make_scan_root(tmp_path: Path) -> Path:
    """A scan_root with a few .py files of known sizes."""
    root = tmp_path / "scan"
    root.mkdir()
    (root / "small.py").write_text("x = 1\n")
    (root / "medium.py").write_text("y = 2\n" * 20)
    (root / "large.py").write_text("z = 3\n" * 200)
    (root / "huge.py").write_text("w = 4\n" * 500)
    return root


def test_largest_files_verify_correct(tmp_path: Path):
    root = _make_scan_root(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    # The actual largest 3: huge, large, medium.
    (out / "largest_files.txt").write_text(
        "huge.py 2000\nlarge.py 800\nmedium.py 80\n"
    )
    task = LargestFilesTask()
    correct, note = task.verify(out, root)
    assert correct is True
    assert "match" in note


def test_largest_files_verify_wrong(tmp_path: Path):
    root = _make_scan_root(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    (out / "largest_files.txt").write_text("small.py 8\n")
    task = LargestFilesTask()
    correct, note = task.verify(out, root)
    assert correct is False
    assert "mismatch" in note


def test_largest_files_verify_missing(tmp_path: Path):
    root = _make_scan_root(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    task = LargestFilesTask()
    correct, note = task.verify(out, root)
    assert correct is False
    assert "missing" in note


def test_fibonacci_verify_correct(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "fib.txt").write_text("55\n")
    task = FibonacciTask()
    correct, note = task.verify(out, tmp_path)
    assert correct is True


def test_fibonacci_verify_wrong(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    (out / "fib.txt").write_text("54\n")
    task = FibonacciTask()
    correct, note = task.verify(out, tmp_path)
    assert correct is False
    assert "54" in note


def test_fibonacci_verify_missing(tmp_path: Path):
    out = tmp_path / "out"
    out.mkdir()
    task = FibonacciTask()
    correct, note = task.verify(out, tmp_path)
    assert correct is False
    assert "missing" in note


def test_synthesis_verify_correct(tmp_path: Path):
    root = tmp_path / "scan"
    root.mkdir()
    (root / "input_a.txt").write_text("alpha fact\n")
    (root / "input_b.txt").write_text("beta fact\n")
    out = tmp_path / "out"
    out.mkdir()
    (out / "synthesis.md").write_text("# S\n- alpha fact\n- beta fact\n")
    task = SynthesisTask()
    correct, note = task.verify(out, root)
    assert correct is True


def test_synthesis_verify_missing_fact(tmp_path: Path):
    root = tmp_path / "scan"
    root.mkdir()
    (root / "input_a.txt").write_text("alpha fact\n")
    (root / "input_b.txt").write_text("beta fact\n")
    out = tmp_path / "out"
    out.mkdir()
    (out / "synthesis.md").write_text("# S\n- alpha fact\n")
    task = SynthesisTask()
    correct, note = task.verify(out, root)
    assert correct is False
    assert "beta fact" in note


def test_synthesis_verify_missing_output(tmp_path: Path):
    root = tmp_path / "scan"
    root.mkdir()
    (root / "input_a.txt").write_text("alpha fact\n")
    (root / "input_b.txt").write_text("beta fact\n")
    out = tmp_path / "out"
    out.mkdir()
    task = SynthesisTask()
    correct, note = task.verify(out, root)
    assert correct is False
    assert "missing" in note


def test_base_task_verify_raises():
    task = BenchmarkTask(id="x", description="x")
    with pytest.raises(NotImplementedError):
        task.verify(Path("out"), Path("scan"))


def test_registry_has_three_tasks_and_find():
    assert [t.id for t in ALL_TASKS] == ["discovery", "codegen", "synthesis"]
    assert find_task("codegen").id == "codegen"
    with pytest.raises(KeyError):
        find_task("nope")


# --------------------------------------------------------------------------- #
# Runner with MockDriver
# --------------------------------------------------------------------------- #


def test_run_benchmark_mock_solves_task(tmp_path: Path):
    """A task the script solves must verify correct=True."""
    task = FibonacciTask()
    runs = run_benchmark(
        tasks=[task],
        prompts={"seed": "{task}"},
        results_dir=tmp_path / "results",
        mock=True,
    )
    assert len(runs) == 1
    m = runs[0]
    assert m.task_id == "codegen"
    assert m.status == "completed"
    assert m.correct is True
    assert m.passed is True


def test_run_benchmark_mock_fails_unsolved_task(tmp_path: Path):
    """A task the script does NOT solve must verify correct=False."""
    # A task whose expected artifact the script never writes.
    class NeverWritesTask(BenchmarkTask):
        def __init__(self) -> None:
            super().__init__(
                id="never",
                description="write never.txt",
                artifact_paths=["never.txt"],
            )

        def verify(self, output_dir: Path, scan_root: Path) -> tuple[bool, str]:
            if (output_dir / "never.txt").exists():
                return True, "present"
            return False, "never.txt missing"

    runs = run_benchmark(
        tasks=[NeverWritesTask()],
        prompts={"seed": "{task}"},
        results_dir=tmp_path / "results",
        mock=True,
    )
    assert len(runs) == 1
    m = runs[0]
    assert m.correct is False
    assert m.passed is False


def test_run_benchmark_writes_json_and_md(tmp_path: Path):
    results_dir = tmp_path / "results"
    run_benchmark(
        tasks=[FibonacciTask()],
        prompts={"seed": "{task}"},
        results_dir=results_dir,
        mock=True,
    )
    json_path = results_dir / "metrics.json"
    md_path = results_dir / "metrics.md"
    assert json_path.exists()
    assert md_path.exists()
    data = json.loads(json_path.read_text())
    assert isinstance(data, list)
    assert data[0]["task_id"] == "codegen"
    assert data[0]["correct"] is True
    assert "Benchmark Metrics Report" in md_path.read_text()


def test_run_benchmark_fresh_runtime_per_pair(tmp_path: Path):
    """Each (prompt, task) pair must get a fresh Runtime (fresh agent ids)."""
    seen_runtimes: list[int] = []

    def factory():
        from dhc.wiring import build_runtime

        rt = build_runtime(mock=True)
        seen_runtimes.append(id(rt))
        return rt

    run_benchmark(
        tasks=[FibonacciTask(), LargestFilesTask()],
        prompts={"seed": "{task}"},
        runtime_factory=factory,
        results_dir=tmp_path / "results",
        mock=True,
    )
    assert len(seen_runtimes) == 2
    assert len(set(seen_runtimes)) == 2  # distinct Runtime objects


def test_stage_workspace_copies_inputs(tmp_path: Path):
    (tmp_path / "input_a.txt").write_text("alpha\n")
    task = SynthesisTask()
    ws = stage_workspace(task, base_dir=tmp_path)
    try:
        # input_a.txt is copied from base_dir; input_b.txt is seeded by
        # stage_inputs (no source file exists in base_dir).
        assert (ws / "input_a.txt").exists()
        assert (ws / "input_b.txt").exists()
        assert (ws / "input_b.txt").read_text().strip() == "beta fact"
    finally:
        import shutil

        shutil.rmtree(ws, ignore_errors=True)


def test_task_script_covers_all_tasks():
    for task in ALL_TASKS:
        script = _task_script(task)
        assert isinstance(script, list) and script, f"no script for {task.id}"


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def test_metrics_passed_logic():
    ok = collect_metrics(prompt_id="p", task_id="t", status="completed", correct=True)
    assert ok.passed is True

    wrong = collect_metrics(prompt_id="p", task_id="t", status="completed", correct=False)
    assert wrong.passed is False

    failed = collect_metrics(prompt_id="p", task_id="t", status="failed", correct=True)
    assert failed.passed is False

    escalated = collect_metrics(prompt_id="p", task_id="t", status="escalated", correct=None)
    assert escalated.passed is False

    unknown = collect_metrics(prompt_id="p", task_id="t", status="completed", correct=None)
    assert unknown.passed is False


def test_metrics_derived_properties():
    m = collect_metrics(
        prompt_id="p", task_id="t", status="completed", correct=True,
        total_tokens=100, cost_usd=0.002, agent_count=2,
    )
    assert m.cost_per_1k == 2.0
    assert m.tokens_per_agent == 50.0


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #


def _run(correct: bool, cost: float = 1.0, tokens: int = 100, turns: int = 5,
         depth: int = 1, latency: float = 1.0) -> RunMetrics:
    return collect_metrics(
        prompt_id="p", task_id="t", status="completed", correct=correct,
        cost_usd=cost, total_tokens=tokens, total_turns=turns,
        max_depth=depth, latency_s=latency,
    )


def test_scoring_correctness_dominates():
    """A correct-but-expensive run must outscore an incorrect-cheap run."""
    correct_expensive = _run(correct=True, cost=10.0, tokens=1000, turns=50, depth=5, latency=10.0)
    incorrect_cheap = _run(correct=False, cost=0.001, tokens=1, turns=1, depth=0, latency=0.01)

    s_correct = score(correct_expensive, best=incorrect_cheap)
    s_incorrect = score(incorrect_cheap, best=incorrect_cheap)

    assert s_correct > s_incorrect
    # Correctness weight is 0.60; an incorrect run can never reach it.
    assert s_incorrect < 0.60
    assert s_correct >= 0.60


def test_scoring_best_run_gets_full_efficiency():
    best = _run(correct=True, cost=0.5, tokens=50, turns=2, depth=0, latency=0.5)
    worse = _run(correct=True, cost=2.0, tokens=200, turns=8, depth=2, latency=2.0)

    s_best = score(best, best=best)
    s_worse = score(worse, best=best)

    assert s_best > s_worse
    # Best run: correctness (0.60) + full efficiency (0.40) = 1.0.
    assert s_best == pytest.approx(1.0)


def test_scoring_weights_total():
    w = ScoringWeights()
    assert w.total() == pytest.approx(1.0)


def test_scoring_deterministic():
    m = _run(correct=True)
    assert score(m) == score(m)