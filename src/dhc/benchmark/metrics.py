"""Per-(prompt, task) run metrics schema.

This module defines the objective, comparable metrics captured for a single
benchmark run (one prompt applied to one task). ``correct`` is the only
*failable* signal: it is set by an external ground-truth verifier, never by
the agent.

Token accounting is the comparison currency. The benchmarked provider exposes
no usable price, so ``cost_usd`` stays 0.0 and is *unmeasured*, not free; the
metric that decides the vision bet is ``tokens_per_resolved_task``
(:class:`TokenSummary`, :mod:`dhc.benchmark.baseline`). ``usage_recorded``
separates "the seam reported zero tokens" from "no usage was ever reported" —
without it a mock run and a zero-token provider response would look identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence


@dataclass
class RunMetrics:
    """Objective measurements for a single (prompt, task) benchmark run.

    All fields are comparable across runs. ``correct`` is set by the task's
    failable verifier, not by the agent's own report.
    """

    prompt_id: str = ""
    task_id: str = ""

    status: str = "completed"            # completed | failed | escalated
    correct: bool | None = None          # ground-truth verification result
    verification_note: str = ""

    total_tokens: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0               # prompt-cache hits, informational only
    # True when a driver/client on this run actually reported provider usage.
    # False means the counters are zero because nothing was recorded (mock
    # path, usage-less provider) — NOT that zero tokens were billed.
    usage_recorded: bool = False
    # Unmeasured for the benchmarked provider (no price is exposed).
    # Tokens, not currency, are the comparison metric.
    cost_usd: float = 0.0

    agent_count: int = 1                # including root
    max_depth: int = 0                  # 0 = root only (no delegation)
    delegations: int = 0                # number of child agents spawned
    message_count: int = 0              # sum of messages across all agents
    total_turns: int = 0                # sum of LLM iterations across all agents
    llm_retries: int = 0                # total retried LLM calls across all agents
    failures: int = 0                   # number of failed agents
    escalations: int = 0                # number of escalated agents

    latency_s: float = 0.0              # wall-clock for the root run
    extra: dict = field(default_factory=dict)

    @property
    def cost_per_1k(self) -> float:
        return self.cost_usd * 1000.0

    @property
    def tokens_per_agent(self) -> float:
        return self.total_tokens / max(1, self.agent_count)

    @property
    def tokens_per_resolved_task(self) -> float | None:
        """Tokens this run spent to resolve its task, or ``None``.

        ``None`` covers both "the run did not resolve the task" and "no usage
        was recorded" — the two cases where a token figure would be a
        fabricated number rather than a measurement.
        """
        if not self.passed or not self.usage_recorded:
            return None
        return float(self.total_tokens)

    @property
    def passed(self) -> bool:
        """A run passes only when it completed AND the verifier said correct."""
        return self.status == "completed" and self.correct is True


def collect_metrics(
    *,
    prompt_id: str,
    task_id: str,
    status: str,
    correct: bool | None,
    verification_note: str = "",
    total_tokens: int = 0,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cached_tokens: int = 0,
    usage_recorded: bool = False,
    cost_usd: float = 0.0,
    agent_count: int = 1,
    max_depth: int = 0,
    delegations: int = 0,
    message_count: int = 0,
    total_turns: int = 0,
    llm_retries: int = 0,
    failures: int = 0,
    escalations: int = 0,
    latency_s: float = 0.0,
    extra: dict | None = None,
) -> RunMetrics:
    """Build a :class:`RunMetrics` from explicit values (no runtime coupling)."""
    return RunMetrics(
        prompt_id=prompt_id,
        task_id=task_id,
        status=status,
        correct=correct,
        verification_note=verification_note,
        total_tokens=total_tokens,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cached_tokens=cached_tokens,
        usage_recorded=usage_recorded,
        cost_usd=cost_usd,
        agent_count=agent_count,
        max_depth=max_depth,
        delegations=delegations,
        message_count=message_count,
        total_turns=total_turns,
        llm_retries=llm_retries,
        failures=failures,
        escalations=escalations,
        latency_s=latency_s,
        extra=dict(extra or {}),
    )


@dataclass
class TokenSummary:
    """Aggregate token accounting across a run set.

    ``tokens_per_resolved_task`` is the comparison metric for the vision bet;
    it is ``None`` whenever there is nothing honest to divide: no resolved
    task, or no run with recorded usage.
    """

    runs: int = 0
    recorded_runs: int = 0
    resolved_runs: int = 0
    resolved_recorded_runs: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    total_tokens: int = 0
    tokens_per_resolved_task: float | None = None

    @property
    def complete(self) -> bool:
        """True when every run in the set reported usage."""
        return self.runs > 0 and self.recorded_runs == self.runs

    def to_dict(self) -> dict:
        return {
            "runs": self.runs,
            "recorded_runs": self.recorded_runs,
            "resolved_runs": self.resolved_runs,
            "resolved_recorded_runs": self.resolved_recorded_runs,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "total_tokens": self.total_tokens,
            "tokens_per_resolved_task": self.tokens_per_resolved_task,
            "cost_usd": None,  # unmeasured: the provider exposes no price
        }


def summarize_tokens(runs: Sequence[RunMetrics]) -> TokenSummary:
    """Aggregate tokens across *runs*, per resolved task.

    Only runs with recorded usage contribute tokens, and the per-task
    denominator counts only resolved runs that also reported usage — dividing
    measured tokens by tasks whose usage was never recorded would understate
    the cost of each resolved task. ``complete``/``recorded_runs`` expose the
    partial-coverage case rather than hiding it. The numerator includes tokens
    spent on attempts that failed: that is the real token cost of the tasks
    that did resolve.

    Resolution is ``RunMetrics.passed`` — the failable verifier, not the
    agent's own report.
    """
    recorded = [m for m in runs if m.usage_recorded]
    resolved = sum(1 for m in runs if m.passed)
    resolved_recorded = sum(1 for m in recorded if m.passed)
    total = sum(m.total_tokens for m in recorded)
    per_task: float | None = None
    if resolved_recorded:
        per_task = total / resolved_recorded
    return TokenSummary(
        runs=len(runs),
        recorded_runs=len(recorded),
        resolved_runs=resolved,
        resolved_recorded_runs=resolved_recorded,
        prompt_tokens=sum(m.prompt_tokens for m in recorded),
        completion_tokens=sum(m.completion_tokens for m in recorded),
        cached_tokens=sum(m.cached_tokens for m in recorded),
        total_tokens=total,
        tokens_per_resolved_task=per_task,
    )