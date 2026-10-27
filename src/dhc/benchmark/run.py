"""Run the metric-driven prompt benchmark.

Usage:
  python3 -m dhc.benchmark.run        # run ALL_TASKS with the default prompt

For each (prompt, task) pair the runner:

  * stages a snapshot workspace (copies the task's input artifacts into a
    temp scan_root),
  * builds a FRESH Runtime (via ``build_runtime(mock=mock)`` or a caller
    ``runtime_factory``),
  * drives a root agent with the prompt (a MockDriver script that does the
    task work, or ``driver_from_settings``),
  * awaits settlement,
  * runs ``task.verify(output_dir, scan_root)`` — the failable ground-truth
    check,
  * records :class:`~dhc.benchmark.metrics.RunMetrics` — including the real
    token counts summed across every agent in the mesh (the usage seam is
    ``Agent.record_usage``, written by the driver; a run whose driver never
    reports usage is marked ``usage_recorded=False`` instead of being
    reported as a zero-token run), and
  * writes results as JSON + Markdown under ``results_dir`` (default
    ``.optimize_benchmarks/``).

Tokens per resolved task is the comparison metric. ``cost_usd`` is left at
0.0 and is *not measured*: the provider exposes no usable price, so no cost
model is built here. Use :mod:`dhc.benchmark.baseline` (``baseline=`` /
``--baseline`` / ``--save-baseline``) to compare against a stored reference.

A fresh Runtime per (prompt, task) keeps usage counters and the task graph
attributable to exactly this run.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from ..data.config import get_settings
from ..llm.driver import MockDriver, driver_from_settings
from ..data.models import AgentStatus
from ..framework.runtime import Runtime
from ..wiring import build_runtime
from .baseline import (
    BaselineError,
    TokenBaseline,
    TokenComparison,
    baseline_from_runs,
    compare_to_baseline,
    load_baseline,
    save_baseline,
)
from .metrics import RunMetrics, collect_metrics, summarize_tokens
from .scoring import format_scores
from .tasks import ALL_TASKS, BenchmarkTask

#: Default results directory (mirrors the reference's .optimize_benchmarks/).
DEFAULT_RESULTS_DIR = ".optimize_benchmarks"

#: The default prompt id used by the CLI.
DEFAULT_PROMPT_ID = "seed"


class BenchmarkRunError(Exception):
    """Raised when a benchmark run cannot be executed."""


@contextmanager
def _cwd(path: Path) -> Iterator[None]:
    """Temporarily change the process CWD (the agent's bash tool resolves here)."""
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def stage_workspace(
    task: BenchmarkTask,
    *,
    base_dir: Path | None = None,
    keep: bool = False,
) -> Path:
    """Create a snapshot workspace for one task run.

    Copies the task's ``artifact_paths`` (input files) into a fresh temp
    directory that becomes the scan_root. The agent writes its outputs into
    the same directory, so ``verify(output_dir, scan_root)`` sees both the
    staged inputs and the produced artifacts.
    """
    base = base_dir or Path.cwd()
    ws = Path(tempfile.mkdtemp(prefix=f"bench_{task.id}_", dir=str(base)))
    try:
        for rel in task.artifact_paths:
            src = base / rel
            if src.exists():
                dst = ws / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        task.stage_inputs(ws)
    except Exception:
        if not keep:
            shutil.rmtree(ws, ignore_errors=True)
        raise
    return ws


def _default_runtime_factory(mock: bool) -> Callable[[], Runtime]:
    def factory() -> Runtime:
        return build_runtime(mock=mock)
    return factory


def _task_script(task: BenchmarkTask) -> list[str]:
    """A MockDriver script that performs the task work (for mock mode).

    Each script writes the expected artifact into the workspace (CWD) and
    completes. This lets the runner exercise the full runtime path — spawn,
    turn execution, settlement — deterministically, with the failable
    verifier deciding correctness.
    """
    if task.id == "discovery":
        return [
            "import glob, os\n"
            "files = []\n"
            "for p in glob.glob('**/*.py', recursive=True):\n"
            "    if any(x in p for x in ('.git', '__pycache__', '.optimize_benchmarks', '.dynamic-harness')):\n"
            "        continue\n"
            "    files.append((p, os.path.getsize(p)))\n"
            "files.sort(key=lambda t: -t[1])\n"
            "with open('largest_files.txt', 'w') as f:\n"
            "    for p, s in files[:3]:\n"
            "        f.write(f'{p} {s}\\n')\n"
            "complete('wrote largest_files.txt')",
        ]
    if task.id == "codegen":
        return [
            "with open('fib.txt', 'w') as f:\n"
            "    f.write('55')\n"
            "complete('wrote fib.txt')",
        ]
    if task.id == "synthesis":
        return [
            "facts = []\n"
            "for name in ('input_a.txt', 'input_b.txt'):\n"
            "    with open(name) as f:\n"
            "        facts.append(f.readline().strip())\n"
            "with open('synthesis.md', 'w') as f:\n"
            "    f.write('# Synthesis\\n')\n"
            "    for fact in facts:\n"
            "        f.write(f'- {fact}\\n')\n"
            "complete('wrote synthesis.md')",
        ]
    return ["complete('no-op')"]


def _run_one(
    *,
    task: BenchmarkTask,
    prompt_id: str,
    prompt: str,
    runtime_factory: Callable[[], Runtime],
    workspace: Path,
    mock: bool,
    driver_factory: Callable[[BenchmarkTask], Any] | None = None,
) -> RunMetrics:
    """Run one (prompt, task) pair against a fresh Runtime and verify it."""
    rt = runtime_factory()
    rt.start()

    if driver_factory is not None:
        driver: Any = driver_factory(task)
    elif mock:
        driver = MockDriver(_task_script(task))
    else:
        driver = driver_from_settings(get_settings(), mock=False)

    t0 = time.monotonic()
    try:
        with _cwd(workspace):
            handle = rt.spawn(prompt, driver=driver)
            completion = handle.await_()
    finally:
        latency = time.monotonic() - t0
        rt.stop()

    status = completion.status.value if completion.status else "unknown"
    if status == "completed":
        status = "completed"
    elif status in ("failed", "cancelled"):
        status = "failed" if status != "cancelled" else "escalated"

    correct: bool | None = None
    note = ""
    try:
        correct, note = task.verify(workspace, workspace)
    except Exception as exc:  # noqa: BLE001 - a verifier bug must not kill the run
        correct, note = False, f"verifier error: {exc}"

    # Derive structural metrics from the runtime's public API.
    agent_count = len(rt._agents) if hasattr(rt, "_agents") else 1
    delegations = max(0, agent_count - 1)
    max_depth = 0
    for agent_id in list(getattr(rt, "_agents", {})):
        depth = _agent_depth(rt, agent_id)
        max_depth = max(max_depth, depth)
    total_turns = _count_turns(rt)

    usage = _aggregate_usage(rt)
    usage_recorded = _usage_recorded(rt, driver)

    return collect_metrics(
        prompt_id=prompt_id,
        task_id=task.id,
        status=status,
        correct=correct,
        verification_note=note,
        total_tokens=usage["prompt_tokens"] + usage["completion_tokens"],
        prompt_tokens=usage["prompt_tokens"],
        completion_tokens=usage["completion_tokens"],
        cached_tokens=usage["cached_tokens"],
        usage_recorded=usage_recorded,
        cost_usd=0.0,  # unmeasured: the provider exposes no usable price
        agent_count=agent_count,
        max_depth=max_depth,
        delegations=delegations,
        message_count=0,
        total_turns=total_turns,
        llm_retries=0,
        failures=0,
        escalations=0,
        latency_s=round(latency, 3),
        extra={"mock": mock, "cost_usd_measured": False},
    )


def _aggregate_usage(rt: Runtime) -> dict[str, int]:
    """Sum the usage counters of every agent in the mesh.

    The counters are the ones ``Agent.record_usage`` (the driver seam)
    accumulates — one agent's calls are indistinguishable from another's
    once summed, which is exactly right for "what did this run cost in
    tokens". Agents that never received usage contribute their zeros.
    """
    agg = {"prompt_tokens": 0, "completion_tokens": 0, "cached_tokens": 0}
    for agent in list(getattr(rt, "_agents", {}).values()):
        agg["prompt_tokens"] += int(getattr(agent, "prompt_tokens", 0) or 0)
        agg["completion_tokens"] += int(getattr(agent, "completion_tokens", 0) or 0)
        agg["cached_tokens"] += int(getattr(agent, "cached_tokens", 0) or 0)
    return agg


def _usage_recorded(rt: Runtime, driver: Any) -> bool:
    """True when provider usage was reported for this run.

    Zero tokens and "no usage recorded" are different facts: ``MockDriver``
    never calls ``record_usage`` (see its docstring) and a provider that
    returns no usage object reports nothing, so their zero counters must not
    be read as a measured zero. Any non-zero counter (from any agent in the
    mesh) proves the seam ran; otherwise the root driver's client decides —
    a client that recorded a ``_last_usage`` measured even when the counts
    are zero.
    """
    usage = _aggregate_usage(rt)
    if any(usage.values()):
        return True
    client = getattr(driver, "_client", None)
    if client is None:
        return False
    return getattr(client, "_last_usage", None) is not None


def _agent_depth(rt: Runtime, agent_id: str) -> int:
    """Depth of *agent_id* in the task graph (0 = root)."""
    depth = 0
    seen: set[str] = set()
    current = agent_id
    while current in getattr(rt, "_agents", {}) and current not in seen:
        seen.add(current)
        agent = rt._agents[current]
        parent = getattr(agent, "parent_id", None)
        if parent is None or parent not in getattr(rt, "_agents", {}):
            break
        depth += 1
        current = parent
    return depth


def _count_turns(rt: Runtime) -> int:
    """Count executed turns from the runtime's event streams (public API)."""
    total = 0
    for agent_id in list(getattr(rt, "_agents", {})):
        events = rt.events(agent_id)
        total += sum(1 for e in events if getattr(e, "kind", None) is not None and e.kind.value == "turn_started")
    return total


def _metrics_to_dict(m: RunMetrics) -> dict:
    return {
        "prompt_id": m.prompt_id,
        "task_id": m.task_id,
        "status": m.status,
        "correct": m.correct,
        "verification_note": m.verification_note,
        "total_tokens": m.total_tokens,
        "prompt_tokens": m.prompt_tokens,
        "completion_tokens": m.completion_tokens,
        "cached_tokens": m.cached_tokens,
        "usage_recorded": m.usage_recorded,
        "tokens_per_resolved_task": m.tokens_per_resolved_task,
        "cost_usd": round(m.cost_usd, 6),  # 0.0 = unmeasured, not free
        "agent_count": m.agent_count,
        "max_depth": m.max_depth,
        "delegations": m.delegations,
        "message_count": m.message_count,
        "total_turns": m.total_turns,
        "llm_retries": m.llm_retries,
        "failures": m.failures,
        "escalations": m.escalations,
        "latency_s": round(m.latency_s, 2),
        "extra": m.extra or None,
    }


def write_results_json(runs: list[RunMetrics], path: Path) -> None:
    """Write per-run metrics as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([_metrics_to_dict(r) for r in runs], indent=2))


def _row(m: RunMetrics) -> str:
    mark = {True: "PASS", False: "FAIL", None: "n.a."}.get(m.correct, "?")
    tokens = f"{m.total_tokens:>9}" if m.usage_recorded else f"{'n/a':>9}"
    per_task = m.tokens_per_resolved_task
    per_task_col = f"{per_task:>10.1f}" if per_task is not None else f"{'—':>10}"
    return (
        f"| {m.prompt_id:<8} | {m.task_id:<10} | {mark:<5} | {tokens} | "
        f"{per_task_col} | {m.total_turns:>6} | {m.max_depth:>5} | "
        f"{m.agent_count:>6} | {m.delegations:>7} | {m.latency_s:>6.1f} |"
    )


def write_results_markdown(
    runs: list[RunMetrics],
    path: Path,
    comparison: TokenComparison | None = None,
) -> None:
    """Write per-run metrics as a Markdown report.

    Cost is absent from the table on purpose: the benchmarked provider
    exposes no price, so USD would be a fabricated column. Tokens per
    resolved task is the comparison metric.
    """
    summary = summarize_tokens(runs)
    lines: list[str] = [
        "# Benchmark Metrics Report",
        "",
        "Per (prompt, task) run — objective, comparable.",
        "",
        "Cost (USD) is **not measured**: the provider exposes no usable price, "
        "so no cost model is applied. Tokens per resolved task is the "
        "comparison metric; `n/a` means no usage was recorded.",
        "",
        "| Prompt | Task | Verdict | Tokens | Tok/resolved | Turns | Depth | Agents | Deleg | Lat(s) |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for m in runs:
        lines.append(_row(m))
    lines += [
        "",
        "## Tokens per resolved task",
        "",
        f"- runs: {summary.runs} ({summary.recorded_runs} with recorded usage)",
        f"- resolved: {summary.resolved_runs} "
        f"({summary.resolved_recorded_runs} with recorded usage)",
        f"- prompt: {summary.prompt_tokens}, completion: {summary.completion_tokens}, "
        f"cached: {summary.cached_tokens}, total: {summary.total_tokens}",
        "- tokens per resolved task: "
        + (
            f"{summary.tokens_per_resolved_task:.1f}"
            if summary.tokens_per_resolved_task is not None
            else "n/a (no recorded usage or no resolved task)"
        ),
    ]
    if comparison is not None:
        lines.append(f"- baseline: {comparison.format_line()}")
    lines += ["", "## Scores", "", "```", format_scores(runs), "```", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))


def write_summary_json(
    runs: list[RunMetrics],
    path: Path,
    comparison: TokenComparison | None = None,
) -> None:
    """Write the token aggregate (and baseline comparison, if any) as JSON."""
    payload: dict[str, Any] = summarize_tokens(runs).to_dict()
    if comparison is not None:
        payload["baseline_comparison"] = comparison.to_dict()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def run_benchmark(
    tasks: list[BenchmarkTask] | None = None,
    prompts: dict[str, str] | None = None,
    runtime_factory: Callable[[], Runtime] | None = None,
    results_dir: str | Path | None = None,
    mock: bool = True,
    driver_factory: Callable[[BenchmarkTask], Any] | None = None,
    baseline: TokenBaseline | str | Path | None = None,
    save_baseline_to: str | Path | None = None,
    baseline_label: str = "baseline",
) -> list[RunMetrics]:
    """Run every (prompt, task) pair and return the collected metrics.

    * ``tasks`` — the tasks to run (default: :data:`ALL_TASKS`).
    * ``prompts`` — maps prompt_id -> prompt text (default: one "seed" prompt
      built from the task description).
    * ``runtime_factory`` — callable returning a fresh Runtime per run
      (default: ``build_runtime(mock=mock)``).
    * ``results_dir`` — where ``metrics.json``, ``metrics.md`` and
      ``summary.json`` are written (default: ``.optimize_benchmarks/``).
    * ``mock`` — when True (default) the root agent is driven by a
      deterministic MockDriver script that performs the task work; when False
      a real LLM driver is used.
    * ``driver_factory`` — optional ``task -> driver`` override (e.g. an
      ``LLMDriver`` over a usage-reporting fake client in tests). Takes
      precedence over ``mock``.
    * ``baseline`` — a :class:`TokenBaseline` or a path to a stored baseline
      JSON; when given, the token aggregate in ``summary.json``/``metrics.md``
      includes the comparison.
    * ``save_baseline_to`` — write this run set as the reference baseline
      (tokens per resolved task) at that path.
    """
    tasks = list(tasks or ALL_TASKS)
    if prompts is None:
        prompts = {DEFAULT_PROMPT_ID: "{task}"}
    if runtime_factory is None:
        runtime_factory = _default_runtime_factory(mock)
    results_dir = Path(results_dir or DEFAULT_RESULTS_DIR)
    if isinstance(baseline, (str, Path)):
        baseline = load_baseline(baseline)

    all_runs: list[RunMetrics] = []
    for prompt_id, prompt_template in prompts.items():
        for task in tasks:
            prompt = prompt_template.format(task=task.description) if "{task}" in prompt_template else prompt_template
            workspace = stage_workspace(task)
            try:
                metrics = _run_one(
                    task=task,
                    prompt_id=prompt_id,
                    prompt=prompt,
                    runtime_factory=runtime_factory,
                    workspace=workspace,
                    mock=mock,
                    driver_factory=driver_factory,
                )
            finally:
                shutil.rmtree(workspace, ignore_errors=True)
            all_runs.append(metrics)

    comparison = compare_to_baseline(all_runs, baseline) if baseline is not None else None
    if save_baseline_to is not None:
        save_baseline(baseline_from_runs(baseline_label, all_runs), save_baseline_to)

    write_results_json(all_runs, results_dir / "metrics.json")
    write_results_markdown(all_runs, results_dir / "metrics.md", comparison)
    write_summary_json(all_runs, results_dir / "summary.json", comparison)
    return all_runs


def main(argv: list[str] | None = None) -> int:
    """CLI entry: run ALL_TASKS with the default prompt, print a table."""
    parser = argparse.ArgumentParser(description="dhc benchmark runner")
    parser.add_argument(
        "--results-dir",
        default=DEFAULT_RESULTS_DIR,
        help="directory for metrics.json / metrics.md (default: %(default)s)",
    )
    parser.add_argument(
        "--real",
        action="store_true",
        help="use the real LLM driver instead of the deterministic mock",
    )
    parser.add_argument(
        "--baseline",
        default=None,
        help="path to a stored token baseline to compare against",
    )
    parser.add_argument(
        "--save-baseline",
        default=None,
        metavar="PATH",
        help="write this run set's tokens per resolved task as a baseline",
    )
    parser.add_argument(
        "--baseline-label",
        default="baseline",
        help="label for --save-baseline (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    try:
        runs = run_benchmark(
            tasks=ALL_TASKS,
            prompts={DEFAULT_PROMPT_ID: "{task}"},
            results_dir=args.results_dir,
            mock=not args.real,
            baseline=args.baseline,
            save_baseline_to=args.save_baseline,
            baseline_label=args.baseline_label,
        )
    except BaselineError as exc:
        print(f"baseline error: {exc}")
        return 2

    print(format_scores(runs))
    summary = summarize_tokens(runs)
    if summary.tokens_per_resolved_task is not None:
        print(f"\nTokens per resolved task: {summary.tokens_per_resolved_task:.1f} "
              f"({summary.recorded_runs}/{summary.runs} runs recorded usage)")
    else:
        print("\nTokens per resolved task: n/a (no recorded usage or nothing resolved)")
    print(f"Results written to {Path(args.results_dir) / 'metrics.json'}, "
          f"{Path(args.results_dir) / 'metrics.md'} and "
          f"{Path(args.results_dir) / 'summary.json'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())