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

The directory tree mirrors `src/dhc/` — the framework/composition split of
decision 0016 is visible here too: `framework/` tests the control loop,
`tooling/` tests the composed agent world, `ui/` tests the operator's side.

| directory | tests |
|---|---|
| `framework/` | `test_runtime`, `test_repl`, `test_repl_resumable`, `test_event_stream`, `test_event_fanout`, `test_context`, `test_core_tooling_boundary` (the framework↔tooling↔ui guard), `test_direct_messaging` (the `send` primitive, 0015), `test_rot_policy`, `test_token_cost`, `test_h04_monotonic_timebase`, `test_h07_legacy_loop`, `test_g05_parked_time`, `test_composition_wave1` |
| `llm/` | `test_llm`, `test_prompts`, `test_prompt_assembly` |
| `ui/` | `test_terminal`, `test_operator`, `test_state` (the operator's review files), `test_checkpoint_split` + `test_checkpoint_trace` (the operator's resumability store, 0012 — moved with their modules in 0016) |
| `data/` | `test_models`, `test_config` |
| `tooling/` | `test_artifact_store` (0014), `test_channels` + `test_channel_tools` (0015: channels are tooling over the core `send` primitive), `test_framework_tools` + `test_events_tool` (the framework-surface tools, moved out of the framework package in 0016), `test_fabrication` (the default agent, moved from `llm/` by 0017) |
| `benchmark/` | `test_benchmark` |
| (top) | `test_imp001_acceptance` — D1–D5 end-to-end acceptance fixture; `test_integration` — the real modules wired by `build_runtime` |

Filing rule: mirror by primary subject (the module's package is the test's
directory). Cross-cutting files stay at the top.

## Baseline

Current baseline (post-restructure, commit 1): **394 passed / 0 failed /
0 skipped**.
