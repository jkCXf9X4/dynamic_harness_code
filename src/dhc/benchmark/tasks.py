"""Benchmark tasks with failable, ground-truth verifiers.

Adopts the reference project's evaluation-task pattern: each task carries a
deterministic verifier that can actually *fail* a run by comparing the
agent-produced artifact against computed ground truth. This gives the
optimization loop statistical power — "success" is not the agent's own
report, it is an external, falsifiable check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


_IGNORE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".optimize_benchmarks",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
    ".dynamic-harness",
}


def _iter_python_files(root: Path):
    for p in sorted(root.rglob("*.py")):
        if any(part in _IGNORE_DIRS for part in p.parts):
            continue
        yield p


def _py_files_by_size(root: Path, top_n: int = 3) -> list[tuple[str, int]]:
    """Ground truth: the largest N .py files by byte size, descending."""
    files = [(str(p.relative_to(root)), p.stat().st_size) for p in _iter_python_files(root)]
    files.sort(key=lambda t: -t[1])
    return files[:top_n]


def _parse_largest_file(out: Path) -> set[tuple[str, int]]:
    """Parse the agent-produced largest-files report into (path, size) tuples."""
    if not out.exists():
        return set()
    parsed: set[tuple[str, int]] = set()
    for line in out.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        parts = re.split(r"\s+", line)
        for tok in parts:
            m = re.match(r"(\d+)", tok)
            if m:
                size = int(m.group(0))
                # remaining tokens (minus the size) form the path
                path = " ".join(t for t in parts if t != tok).strip()
                if path:
                    parsed.add((path.replace("./", ""), size))
                break
    return parsed


@dataclass
class BenchmarkTask:
    """A benchmark task: description + failable ground-truth verifier.

    ``artifact_paths`` lists the relative paths (under the staged workspace)
    the agent is expected to produce. ``verify`` MUST be falsifiable: it
    returns ``(correct, note)`` by comparing the agent's output against
    computed ground truth, never by trusting the agent's own report.
    """

    id: str
    description: str
    artifact_paths: list[str] = field(default_factory=list)

    def stage_inputs(self, workspace: Path) -> None:
        """Seed the staged workspace with the task's input files.

        Called by the runner after the snapshot workspace is created, before
        the agent runs. The default is a no-op; tasks with inputs (e.g. the
        synthesis sources) override this to create them deterministically.
        """
        del workspace  # default: no inputs to seed

    def verify(self, output_dir: Path, scan_root: Path) -> tuple[bool, str]:
        """Return (correct, note). MUST be falsifiable."""
        raise NotImplementedError


class LargestFilesTask(BenchmarkTask):
    """Discovery probe: find the N largest Python files under scan_root."""

    def __init__(self, top_n: int = 3) -> None:
        self.top_n = top_n
        super().__init__(
            id="discovery",
            description=(
                f"Find the {top_n} largest Python files in the current "
                "directory. Write the results (paths with sizes, sorted "
                "descending) to largest_files.txt and report with that "
                "artifact."
            ),
            artifact_paths=["largest_files.txt"],
        )

    def stage_inputs(self, workspace: Path) -> None:
        """Seed a few .py files of distinct sizes so the scan has ground truth."""
        seeds = {
            "alpha.py": "a = 1\n",
            "beta.py": "b = 2\n" * 20,
            "gamma.py": "c = 3\n" * 200,
            "delta.py": "d = 4\n" * 500,
        }
        for name, body in seeds.items():
            (workspace / name).write_text(body)

    def verify(self, output_dir: Path, scan_root: Path) -> tuple[bool, str]:
        truth = _py_files_by_size(scan_root, top_n=self.top_n)
        produced = _parse_largest_file(output_dir / "largest_files.txt")

        if not produced:
            return False, "artifact missing or unparseable"

        truth_paths = {t[0] for t in truth}
        produced_paths = {p for p, _ in produced}

        if truth_paths != produced_paths:
            missing = truth_paths - produced_paths
            extra = produced_paths - truth_paths
            return False, f"mismatch: missing={sorted(missing)} extra={sorted(extra)}"

        return True, f"top-{self.top_n} match: {sorted(truth_paths)}"


class FibonacciTask(BenchmarkTask):
    """Codegen probe: compute fib(10) and write the answer to fib.txt."""

    def __init__(self) -> None:
        super().__init__(
            id="codegen",
            description=(
                "Compute the 10th Fibonacci number (fib(10) = 55, with "
                "fib(0)=0, fib(1)=1). Write the answer as a bare integer to "
                "fib.txt and report with that artifact."
            ),
            artifact_paths=["fib.txt"],
        )

    def verify(self, output_dir: Path, scan_root: Path) -> tuple[bool, str]:
        del scan_root  # ground truth is a constant, not a scan
        out = output_dir / "fib.txt"
        if not out.exists():
            return False, "fib.txt missing"
        text = out.read_text().strip()
        m = re.search(r"\d+", text)
        if m is None:
            return False, f"no integer found in fib.txt: {text!r}"
        got = int(m.group(0))
        if got != 55:
            return False, f"fib(10) = {got}, expected 55"
        return True, "fib(10) = 55 matches ground truth"


class SynthesisTask(BenchmarkTask):
    """Synthesis probe: read two input files, write a synthesis with both facts.

    The two input files are staged into the workspace (via ``artifact_paths``
    on the task instance); the agent must read both and produce
    ``synthesis.md`` containing a key fact from each.
    """

    def __init__(self, sources: list[str] | None = None) -> None:
        #: Relative paths of the input files staged into the workspace.
        self.sources = list(sources or ["input_a.txt", "input_b.txt"])
        super().__init__(
            id="synthesis",
            description=(
                "Read the two input files in the current directory "
                f"({', '.join(self.sources)}). Each file's first line is a "
                "key fact. Write a synthesis to synthesis.md that contains "
                "BOTH key facts (one from each file) and report with that "
                "artifact."
            ),
            artifact_paths=["synthesis.md", *self.sources],
        )

    def stage_inputs(self, workspace: Path) -> None:
        """Create the two source files with deterministic key facts."""
        facts = {
            "input_a.txt": "alpha fact",
            "input_b.txt": "beta fact",
        }
        for name, fact in facts.items():
            (workspace / name).write_text(f"{fact}\n")

    def verify(self, output_dir: Path, scan_root: Path) -> tuple[bool, str]:
        out = output_dir / "synthesis.md"
        if not out.exists():
            return False, "synthesis.md missing"
        text = out.read_text()

        facts: list[str] = []
        for rel in self.sources:
            src = scan_root / rel
            if not src.exists():
                return False, f"input file missing from workspace: {rel}"
            first = src.read_text().splitlines()[0].strip() if src.read_text().splitlines() else ""
            if first:
                facts.append(first)

        missing = [f for f in facts if f not in text]
        if missing:
            return False, f"synthesis missing key facts: {missing}"

        return True, f"synthesis contains all {len(facts)} key facts"


#: The task registry — the set of tasks the benchmark runner executes.
ALL_TASKS: list[BenchmarkTask] = [
    LargestFilesTask(),
    FibonacciTask(),
    SynthesisTask(),
]


def find_task(task_id: str) -> BenchmarkTask:
    """Look up a task by id from the registry."""
    for t in ALL_TASKS:
        if t.id == task_id:
            return t
    raise KeyError(f"unknown task id: {task_id}")