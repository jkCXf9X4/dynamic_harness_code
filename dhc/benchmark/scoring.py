"""Objective scoring of per-run metrics into a comparable rubric score.

The scoring model is explicit and weights are configurable. Correctness is
the primary gate: a run must pass the task's failable verifier to earn credit
on it. Among correct runs, we score *efficiency* (lower cost/tokens/turns/
depth/latency is better) using inverse normalization against the best run in
the batch.

This replaces any subjective "quality of prose" ranking with a fixed,
deterministic, weighted rubric.
"""

from __future__ import annotations

from dataclasses import dataclass

from .metrics import RunMetrics


@dataclass
class ScoringWeights:
    # Correctness dominates; everything else is secondary efficiency.
    correctness: float = 0.60
    cost: float = 0.15
    tokens: float = 0.10
    turns: float = 0.07
    depth: float = 0.04
    latency: float = 0.04

    def total(self) -> float:
        return (
            self.correctness
            + self.cost
            + self.tokens
            + self.turns
            + self.depth
            + self.latency
        )


WEIGHTS = ScoringWeights()


def _inverse_normalize(values: list[float]) -> list[float]:
    """Turn 'lower is better' values into (higher = better) in [0, 1].

    Best (lowest) value maps to 1.0, worst (highest) to 0.0.
    If all values are equal, each maps to 1.0.
    """
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    if hi == lo:
        return [1.0] * len(values)
    return [(hi - v) / (hi - lo) for v in values]


def _efficiency_component(
    metrics: RunMetrics,
    best: RunMetrics,
    weight: float,
    attr: str,
) -> float:
    """Weighted inverse-normalized efficiency for one metric.

    ``best`` is the best (lowest) run in the batch for that metric; a run
    equal to the best scores the full weight, a run at the worst scores 0.
    """
    value = float(getattr(metrics, attr))
    best_value = float(getattr(best, attr))
    if best_value == value:
        return weight
    # Normalize against the best: score = best/value, capped at 1.0.
    if best_value == 0:
        return 0.0 if value > 0 else weight
    return weight * min(1.0, best_value / value)


def score(
    metrics: RunMetrics,
    weights: ScoringWeights | None = None,
    best: RunMetrics | None = None,
) -> float:
    """Deterministic weighted rubric score in [0, 1].

    Correctness dominates: a correct run earns ``weights.correctness``, an
    incorrect run earns 0 for that component. Efficiency components
    (cost/tokens/turns/depth/latency) are inverse-normalized against the
    best run in the batch — pass ``best`` (the run with the lowest values)
    or the run's own values are used (a single-run batch scores full
    efficiency weight, documented normalization: best == self).
    """
    w = weights or WEIGHTS
    if best is None:
        best = metrics

    if metrics.passed:
        correctness = w.correctness
    else:
        correctness = 0.0

    efficiency = (
        _efficiency_component(metrics, best, w.cost, "cost_usd")
        + _efficiency_component(metrics, best, w.tokens, "total_tokens")
        + _efficiency_component(metrics, best, w.turns, "total_turns")
        + _efficiency_component(metrics, best, w.depth, "max_depth")
        + _efficiency_component(metrics, best, w.latency, "latency_s")
    )

    return round(correctness + efficiency, 6)


def format_scores(metrics_list: list[RunMetrics], weights: ScoringWeights | None = None) -> str:
    """Render a small table of per-run scores (for the CLI)."""
    w = weights or WEIGHTS
    if not metrics_list:
        return "(no runs)"
    best = _best_run(metrics_list)
    lines = [
        f"{'Prompt':<12} {'Task':<12} {'Verdict':<6} {'Score':>8}",
        "-" * 44,
    ]
    for m in metrics_list:
        verdict = "PASS" if m.passed else "FAIL"
        lines.append(f"{m.prompt_id:<12} {m.task_id:<12} {verdict:<6} {score(m, w, best):>8.4f}")
    return "\n".join(lines)


def _best_run(metrics_list: list[RunMetrics]) -> RunMetrics:
    """The run with the lowest efficiency values (the normalization anchor)."""
    return min(
        metrics_list,
        key=lambda m: (
            m.cost_usd,
            m.total_tokens,
            m.total_turns,
            m.max_depth,
            m.latency_s,
        ),
    )