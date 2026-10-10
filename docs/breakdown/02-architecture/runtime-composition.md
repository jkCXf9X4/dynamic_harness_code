---
id: INFO-058
type: info
title: Runtime composition
summary: How the wired runtime fits together: operator door, worker threads, event bus, composed operator tooling
date: 2026-10-09
status: current
---

# Runtime composition

```
operator (root door) ──> Runtime ──> per-agent worker thread
                        │             └─> ReplEngine (persistent REPL)
                        │             └─> driver (LLMDriver | MockDriver)
                        ├─> send() — directed messages: the framework's
                        │    communication primitive (AD-009)
                        ├─> EventBus ──> BoundaryEventLog (persist sink)
                        ├─> CompletionDispatcher (at-most-once, FIFO)
                        └─> operator tooling (AD-008/AD-009), composed at the root:
                              ArtifactStore (content-addressed, 3 tiers)
                              channels: Messenger, RoomManager,
                              EscalationChannel, OperatorQuestionChannel
```

- **Build entry point**:
  - `dhc.wiring.build_runtime(settings=None, mock=False)` wires the real modules together.
  - Returns ready `Runtime` with the channels and the operator tooling exposed.

- **Bare vs wired** (`IMD-004`):
  - Bare `Runtime()` (no `repl_engine`, no `_MemoryEngine`) runs on the legacy turn loop.
  - Legacy turn loop: no ceiling caps, no rot tripwire between turns.
  - Every wired runtime (`build_runtime`) runs on the pump under all four hard gates.
  - Production `dhc` CLI constructs the bare form (`cli.py:130`).
  - Core contract tests (`tests/framework/test_runtime.py`, ~27 spawn sites via `make_runtime()`) run on the bare form too.

- **Exposed surfaces**:
  - `runtime.messenger`
  - `runtime.rooms`
  - `runtime.escalations`
  - `runtime.questions`
  - `runtime.operator`
  - `runtime.boundary_log`
  - `runtime.artifact_store`

## Owns
- How the wired runtime fits together: the composition diagram and the `build_runtime` entry point with its exposed surfaces.

## Excludes
- What each module contains: `INFO-055`.
- Dispatch, resolution, and logging guarantees behind the composition: `INFO-047`, `INFO-048`, `INFO-049`.
