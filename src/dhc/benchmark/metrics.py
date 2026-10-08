"""Per-(prompt, task) run metrics schema.

This module defines the objective, comparable metrics captured for a single
benchmark run (one prompt applied to one task). ``correct`` is the only
*failable* signal: it is set by an external ground-truth verifier, never by
the agent.
"""

from __future__ import annotations

from dataclasses import dataclass, field


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