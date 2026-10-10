---
id: INFO-069
type: info
title: The benchmark harness
summary: Ground-truth benchmark tasks with verifiable outcomes, per-run isolation, derived structural metrics, and the weighted scoring rubric
date: 2026-10-10
status: current
---

# The benchmark harness

The evaluation harness in `src/dhc/benchmark/`: ground-truth tasks with failable verifiers, per-(prompt, task) run isolation, derived metrics, weighted scoring. Success is an external, falsifiable check, never the agent's own report.

## Tasks — failable ground truth

- `BenchmarkTask` carries `id`, `description`, `artifact_paths`; `stage_inputs` seeds the staged workspace; `verify(output_dir, scan_root)` returns `(correct, note)`.
- `verify` compares agent output against computed ground truth — never trusts the agent's own report.
- `ALL_TASKS` registers three probes:
  - **`discovery` (LargestFilesTask)**: find the three largest `.py` files by byte size under the scan root; write `largest_files.txt`.
    - `stage_inputs` seeds four `.py` files of distinct sizes.
    - Verify recomputes the top three; fails on missing or extra paths.
  - **`codegen` (FibonacciTask)**: compute fib(10) with fib(0)=0, fib(1)=1; write the bare integer to `fib.txt`.
    - Verify extracts the integer; fails on anything but 55.
  - **`synthesis` (SynthesisTask)**: read `input_a.txt` and `input_b.txt`; write `synthesis.md` holding both first-line key facts.
    - `stage_inputs` creates the two source files with deterministic facts.
    - Verify fails when a key fact is missing.

## Run isolation

- `run_benchmark` iterates every (prompt, task) pair; default prompt id `seed`, template `{task}` filled with the task description.
- `stage_workspace` creates a fresh temp dir (prefix `bench_{task.id}_`), copies inputs, calls `stage_inputs` — it becomes `scan_root`.
- A fresh `Runtime` is built per pair via `build_runtime(mock=mock)` or a caller `runtime_factory`.
  - Fresh runtime keeps usage counters and the task graph attributable to exactly this run.
- `mock=True` (default) drives the root with a deterministic `MockDriver` script that performs the task work; `mock=False` uses `driver_from_settings`.
- Process CWD switches into the workspace for spawn plus await; the agent's file operations resolve there.
- The runner awaits settlement, then calls `task.verify(workspace, workspace)`.
  - A verifier exception becomes incorrect with note `verifier error` — never kills the run.
- The workspace is removed after each pair.

## Metrics

- `RunMetrics` captures one run: ids, `status` (`completed` | `failed` | `escalated`), `correct`, `verification_note`, token counts, `cost_usd`, `agent_count` (including root), `max_depth` (0 = root only), `delegations`, `message_count`, `total_turns`, `llm_retries`, `failures`, `escalations`, `latency_s`.
- `passed` requires status `completed` AND `correct is True`.
- The runner maps outcome: completed stays; failed and timeout become failed; cancelled becomes escalated.
- Structure derives from the runtime: `agent_count` from the agent registry, `delegations` as agent count minus one, `max_depth` via parent-chain walk, `total_turns` by counting `turn_started` events across agent streams.
- Token, cost, message, retry counters are currently recorded as zero; latency is measured.

## Scoring

- Weighted rubric: correctness 0.60, cost 0.15, tokens 0.10, turns 0.07, depth 0.04, latency 0.04.
- Correctness gates: a passed run earns 0.60; a failed run earns 0 for it.
- Efficiency measures (`cost_usd`, `total_tokens`, `total_turns`, `max_depth`, `latency_s`) score against the batch-best run: weight times `min(1.0, best / value)`.
- A single-run batch scores full efficiency weight — best is the run itself.

## Output and CLI

- Results land as `metrics.json` and `metrics.md` under `results_dir`, default `.optimize_benchmarks/`.
- CLI: `python3 -m dhc.benchmark.run` runs `ALL_TASKS` with the default prompt and prints the score table.
- Flags: `--results-dir` overrides the output directory; `--real` selects the real LLM driver instead of the deterministic mock.

## Owns
- The evaluation harness: ground-truth tasks, run isolation, metrics schema, scoring rubric, output files, CLI entry.

## Excludes
- The test suite — `INFO-056`, `INFO-067`.
- Acceptance criteria — `INFO-068`.
- The value demo — `INFO-057`.
- The time base behind latency — `INFO-060`.
