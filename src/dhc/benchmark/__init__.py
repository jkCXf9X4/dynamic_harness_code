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

from .metrics import RunMetrics
from .run import run_benchmark
from .scoring import ScoringWeights, WEIGHTS, score
from .tasks import ALL_TASKS, BenchmarkTask, find_task

__all__ = [
    "ALL_TASKS",
    "BenchmarkTask",
    "RunMetrics",
    "ScoringWeights",
    "WEIGHTS",
    "find_task",
    "run_benchmark",
    "score",
]