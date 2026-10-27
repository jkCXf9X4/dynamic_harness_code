"""Token baseline: compare a run set against stored reference tokens.

The benchmarked provider exposes no usable price, so USD is not a comparison
metric anywhere in this package. The baseline is therefore *tokens per
resolved task* plus the raw token counts that produced it.

A baseline file is a small JSON object::

    {
      "label": "tool-call-path",
      "runs": 3,
      "resolved_tasks": 2,
      "prompt_tokens": 18000,
      "completion_tokens": 2500,
      "cached_tokens": 0,
      "total_tokens": 20500,
      "tokens_per_resolved_task": 10250.0,
      "notes": "measured on the tool-call harness"
    }

It is written by :func:`save_baseline` (or the runner's ``--save-baseline``)
and read back by :func:`load_baseline`; :func:`compare_to_baseline` reports
whether the current run set spends fewer tokens per resolved task.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .metrics import RunMetrics, TokenSummary, summarize_tokens


class BaselineError(Exception):
    """Raised when a baseline cannot be built, saved, or loaded."""


@dataclass
class TokenBaseline:
    """Reference token cost per resolved task for a known-good run set."""

    label: str
    total_tokens: int
    resolved_tasks: int
    runs: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    notes: str = ""

    @property
    def tokens_per_resolved_task(self) -> float:
        """Reference metric. A baseline is only creatable from resolved runs."""
        return self.total_tokens / self.resolved_tasks

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "runs": self.runs,
            "resolved_tasks": self.resolved_tasks,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tokens": self.total_tokens,
            "tokens_per_resolved_task": self.tokens_per_resolved_task,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TokenBaseline":
        try:
            resolved = int(data["resolved_tasks"])
            total = int(data["total_tokens"])
        except (KeyError, TypeError, ValueError) as exc:
            raise BaselineError(f"malformed baseline: {exc}") from exc
        if resolved <= 0:
            raise BaselineError("baseline has no resolved tasks to divide by")
        return cls(
            label=str(data.get("label", "")),
            total_tokens=total,
            resolved_tasks=resolved,
            runs=int(data.get("runs", 0) or 0),
            prompt_tokens=int(data.get("prompt_tokens", 0) or 0),
            completion_tokens=int(data.get("completion_tokens", 0) or 0),
            cached_tokens=int(data.get("cached_tokens", 0) or 0),
            notes=str(data.get("notes", "")),
        )


def baseline_from_runs(
    label: str,
    runs: Sequence[RunMetrics],
    *,
    notes: str = "",
) -> TokenBaseline:
    """Build a baseline from runs whose usage was recorded and that resolved.

    Raises :class:`BaselineError` when nothing usable was measured — a
    baseline of zeros would silently poison every later comparison.
    """
    summary = summarize_tokens(runs)
    if not summary.recorded_runs:
        raise BaselineError("no run in the set reported token usage")
    if not summary.resolved_runs:
        raise BaselineError("no run in the set resolved its task")
    return TokenBaseline(
        label=label,
        total_tokens=summary.total_tokens,
        resolved_tasks=summary.resolved_runs,
        runs=summary.runs,
        prompt_tokens=summary.prompt_tokens,
        completion_tokens=summary.completion_tokens,
        cached_tokens=summary.cached_tokens,
        notes=notes,
    )


def save_baseline(baseline: TokenBaseline, path: str | Path) -> Path:
    """Write *baseline* as JSON (parents created)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline.to_dict(), indent=2) + "\n")
    return path


def load_baseline(path: str | Path) -> TokenBaseline:
    """Read a baseline written by :func:`save_baseline`."""
    path = Path(path)
    try:
        data = json.loads(path.read_text())
    except OSError as exc:
        raise BaselineError(f"cannot read baseline {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BaselineError(f"baseline {path} is not JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise BaselineError(f"baseline {path} must be a JSON object")
    return TokenBaseline.from_dict(data)


@dataclass
class TokenComparison:
    """Current run set vs a stored baseline, in tokens per resolved task.

    ``ratio`` is ``current / baseline``: below 1.0 means fewer tokens per
    resolved task than the reference (the vision bet paying off). ``None``
    means the comparison is not possible — no recorded usage or no resolved
    task on the current side.
    """

    baseline: TokenBaseline
    summary: TokenSummary
    comparable: bool
    current_tokens_per_resolved_task: float | None = None
    ratio: float | None = None
    delta: float | None = None

    def to_dict(self) -> dict:
        return {
            "baseline": self.baseline.to_dict(),
            "current": self.summary.to_dict(),
            "comparable": self.comparable,
            "current_tokens_per_resolved_task": self.current_tokens_per_resolved_task,
            "ratio": self.ratio,
            "delta": self.delta,
        }

    def format_line(self) -> str:
        """One-line human summary for the Markdown report/CLI."""
        base = f"{self.baseline.label}: {self.baseline.tokens_per_resolved_task:.1f} tok/resolved"
        if not self.comparable or self.current_tokens_per_resolved_task is None:
            return f"{base} — current run not comparable (no recorded/resolved usage)"
        cur = self.current_tokens_per_resolved_task
        pct = (self.ratio - 1.0) * 100.0 if self.ratio is not None else 0.0
        return f"{base} → current {cur:.1f} tok/resolved (ratio {self.ratio:.3f}, {pct:+.1f}%)"


def compare_to_baseline(
    runs: Sequence[RunMetrics],
    baseline: TokenBaseline,
) -> TokenComparison:
    """Compare *runs* to *baseline* on tokens per resolved task."""
    summary = summarize_tokens(runs)
    current = summary.tokens_per_resolved_task
    comparable = current is not None
    ratio = delta = None
    if comparable:
        base = baseline.tokens_per_resolved_task
        ratio = current / base
        delta = current - base
    return TokenComparison(
        baseline=baseline,
        summary=summary,
        comparable=comparable,
        current_tokens_per_resolved_task=current,
        ratio=ratio,
        delta=delta,
    )
