---
id: INFO-055
type: info
title: Module map
summary: What each module owns - the layout is the architecture
date: 2026-10-09
status: current
---

# Module map

The layout IS the architecture (decision AD-010): `framework/` runs agents and
enforces guarantees (zero tools inside), `tooling/` is everything installed
into agent REPLs beyond the core actions, `ui/` is the operator's side, and
`wiring.py` is the only meeting point. All modules live under `src/dhc/`.

- **`data/models.py`** — `Artifact`, `Result`, `Event`, `Completion`, `ToolOutput`, `Room`, lifecycle states.
- **`errors.py`** — the `DhcError` hierarchy.
- **`data/config.py`** — `Settings` (env + `.env`), `get_settings()`.
- **`framework/runtime.py`** — `Runtime`: spawn/await/poll/cancel/status/result/send, parent liveness, worker loop. An orchestrator plus re-export facade since the module split (`IMD-001`): the loop, caps, integrity, and context concerns live in their own modules, and the moved callables are re-exported here.
- **`framework/repl.py`** — per-agent persistent `ReplEngine` (`INFO-050`).
- **`framework/event_stream.py`** — `EventStream`, `EventBus`, `CompletionDispatcher` (`INFO-046`, `INFO-047`, `INFO-048`).
- **`framework/agent.py`** — the in-code surface: `Agent`, `AgentHandle`, `bash`, `send` (the directed-message primitive, AD-009).
- **`framework/pump.py`** — the pump: drives agent-authored `__runner__` loops under the hard gates (renamed from `loop.py`, AD-011). Carries both loop paths behind the `pump_agent` dispatch (`IMD-004`): `pump_loop` for wired runtimes (`build_runtime`), `legacy_loop` (decide → execute → settle, turn-based, no caps watchdog, no rot gate) for the bare in-memory core. Dispatch: `supports_pump` is true when `runtime.repl_engine` is set or `runtime.engine` has `advance`; `_MemoryEngine` has no pump primitives, so a bare `Runtime()` (the CLI's shape, `cli.py:130`) always takes the legacy path. Owns the yield vocabulary (`Await`/`Poll`/`Sleep`), `install_runner`/`service_await`/`service_sleep`/`step_timeout`/`supports_pump`, and the parked-time accumulator (`PD-001`).
- **`framework/caps.py`** — the ceiling-caps watchdog predicate plus the five ceiling-cap defaults (`IMD-001`); the wall-clock branch carries the parked-time credit (`PD-001`) on the monotonic base (`AD-007`).
- **`framework/integrity.py`** — the best-effort `ensure_fabrication` re-seed calls (`IMD-001`, `AD-004`).
- **`framework/context.py`** — the context-trigger seam: `DIGEST_KEEP = 50`, `trim_digest`, `make_observe` (the digest observe/trim, the only real pruning) (`IMD-001`); `tooling/fabrication.py`'s `make_observe` delegates to it.
- **`framework/rot.py`** — the pump-side rot tripwire: agent-settable policy, runtime-owned evaluation.
- **Engine pump-primitive matrix** (`IMD-004`): `ReplEngine` (`framework/repl.py`) provides all eight primitives (install/advance/inject/kill/suspend/resume/globals_for/has_workspace) — pump; `_ReplEngineAdapter` (`wiring.py`) wraps `ReplEngine` with `runtime.repl_engine` set alongside — pump; `_MemoryEngine` (`framework/runtime.py`) provides none, only `execute` — legacy. `TracingEngine` (`data/trace.py`) is a test-surface wrapper used directly against an engine (`tests/ui/test_checkpoint_trace.py`), never installed as a `Runtime` engine — not a loop consumer.
- **Legacy-path consumers** (`IMD-004`): the production `dhc` CLI (`cli.py:130`, bare `Runtime(settings=settings)`, every operator request driven through it) and the core contract tests (`make_runtime()` in `tests/framework/test_runtime.py`, ~27 spawn sites; `tests/ui/test_operator.py` via `Operator.run`). The remaining bare-`Runtime()` sites (`test_tools.py:158`, `test_events_tool.py`, `test_state.py`'s `NoBusRuntime`) touch `_build_namespace`/`_emit` directly and never spawn — not loop consumers.
- **`llm/llm.py`** — `LLMClient`, `MockLLM`, `ContextRotDetector` (`INFO-020`, `INFO-021`).
- **`llm/driver.py`** — `LLMDriver`, `MockDriver`, `driver_from_settings` — the pluggable brain.
- **`tooling/fabrication.py`** — the default agent: the fabrication kit a workspace is born with (default `__runner__`, `decide`, context, helpers), handed in via `Runtime(kit_factory=...)` (AD-011).
- **`tooling/framework_tools.py`** — the framework-surface tools: `list_tools`, `events` (moved out of the framework, AD-010).
- **`tooling/artifact_store.py`** — content-addressed `ArtifactStore`, `BoundaryEventLog` (`INFO-049`) — composed tooling (AD-008).
- **`tooling/artifact_tools.py`** — the store's REPL tools: `publish`, `read_artifact`, `archive`, `list_artifacts`.
- **`tooling/channels.py`** — `Messenger`, `RoomManager`, `EscalationChannel`, `OperatorQuestionChannel` — communication policies over the core `send` primitive (AD-009).
- **`tooling/channel_tools.py`** — the channels' REPL tools: `room`, `messenger`, `escalate`, `ask_operator`, `post`, `channel_read`.
- **`ui/operator.py`** — root door, chat loop, mid-turn steering, operator questions.
- **`ui/state.py`** — the operator's review files: tree, stats, events (AD-010).
- **`ui/checkpoint.py`** — the operator's resumability store, surfaced via `/resume` (PD-002).
- **`cli.py`** — minimal chat-only TUI (`INFO-028`).
- **`wiring.py`** — `build_runtime` — the composition root, the only framework+tooling meeting point.

## Owns
- The module map: what each module under `src/dhc/` owns, and the code layout as the boundary.

## Excludes
- How the wired runtime fits together — `INFO-058`.
- What the runtime promises its users and integrators — the Product layer.
