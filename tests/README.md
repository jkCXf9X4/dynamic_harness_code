# tests/

Pytest suite for the `dhc` package. The layout mirrors the package: each
subpackage has a matching test directory, and cross-cutting tests stay at the
top.

## Run

From the repo root:

```bash
.venv/bin/python -m pytest
```

`pyproject.toml` sets `pythonpath = ["src"]`, so the suite runs without an
install (an editable install also works). No test touches the network and
nothing is written into the repo tree — all file I/O goes to pytest
`tmp_path`.

## Layout

| directory | tests |
|---|---|
| `agent/` | `test_runtime`, `test_repl`, `test_repl_resumable`, `test_tools`, `test_state`, `test_event_stream`, `test_checkpoint_trace`, `test_core_tooling_boundary`, `test_direct_messaging` (the `send` primitive, 0015) |
| `llm/` | `test_llm`, `test_fabrication`, `test_prompts` |
| `ui/` | `test_terminal`, `test_operator` |
| `data/` | `test_models`, `test_config` |
| `tooling/` | `test_artifact_store` (0014), `test_channels` + `test_channel_tools` (0015: channels are tooling over the core `send` primitive) |
| `benchmark/` | `test_benchmark` |
| (top) | `test_imp001_acceptance` — D1–D5 end-to-end acceptance fixture; `test_integration` — the real modules wired by `build_runtime` |

19 files total. Filing rule: mirror by primary subject. Combined-subject
files follow their primary module (`test_checkpoint_trace` covers
`agent/checkpoint.py` + `data/trace.py` and is filed under `agent/`);
cross-cutting files stay at the top.

## Baseline

Current baseline (post-restructure, commit 1): **394 passed / 0 failed /
0 skipped**.
