"""dhc benchmark package: failable verifiers, registry, runner, metrics, scoring.

Adopts the reference project's evaluation-task pattern so the harness can be
evaluated objectively:

* :class:`~dhc.benchmark.tasks.BenchmarkTask` — a task with a failable
  ground-truth ``verify()`` that can actually fail a run;
* :data:`~dhc.benchmark.tasks.ALL_TASKS` — the task registry;
* :func:`~dhc.benchmark.run.run_benchmark` — the runner (fresh Runtime per
  (prompt, task), staged workspace, JSON + Markdown results);
* :class:`~dhc.benchmark.metrics.RunMetrics` — objective per-run metrics;
* :class:`~dhc.benchmark.scoring.ScoringWeights` — the deterministic weighted
  rubric.
"""

from __future__ import annotations

from .baseline import (
    TokenBaseline,
    TokenComparison,
    baseline_from_runs,
    compare_to_baseline,
    load_baseline,
    save_baseline,
)
from .metrics import RunMetrics, TokenSummary, summarize_tokens
from .run import run_benchmark
from .scoring import ScoringWeights, WEIGHTS, score
from .tasks import ALL_TASKS, BenchmarkTask, find_task

__all__ = [
    "ALL_TASKS",
    "BenchmarkTask",
    "RunMetrics",
    "ScoringWeights",
    "TokenBaseline",
    "TokenComparison",
    "TokenSummary",
    "WEIGHTS",
    "baseline_from_runs",
    "compare_to_baseline",
    "find_task",
    "load_baseline",
    "run_benchmark",
    "save_baseline",
    "score",
    "summarize_tokens",
]