---
id: INFO-063
type: info
title: Checkpointing and resumability
summary: Two checkpoint mechanisms by design — agent-owned workspace snapshots in the fabrication kit and the operator's on-disk checkpoint store — each resuming a different thing
date: 2026-10-10
status: current
---

# Checkpointing and resumability

Two checkpoint mechanisms exist by design (`PD-002`). Agent side snapshots the workspace; operator side persists turn state to disk.

## Agent-side checkpoints

- `checkpoint(note, done)` appends one record to `state["checkpoints"]` (`tooling/fabrication.py`).
- Record carries `note`, a `done` list, and `snapshot` — a shallow copy of workspace globals.
- Snapshot taken via `dict(engine.globals_for(agent_id))`; stays in-memory, in-workspace.
- `checkpoint` returns the log index.
- `rollback(index)` restores a snapshot through `engine.inject`; latest by default.
- Restore is a best-effort merge; an empty log returns False.
- `compact()` nulls only the transient `result` workspace name.
- All three are `FABRICATION_NAMES` citizens; `ensure_fabrication` re-seeds a broken one (`INFO-037`).
- Agent-callable, ordinary data — the agent reads, edits, and calls them freely.

## Operator-side store

- `AgentCheckpoint` pydantic model: agent_id, requirement, acceptance, status, turn_counter, checkpoint_notes, updated_at, extra (`ui/checkpoint.py`).
- `CheckpointStore` persists one JSON per agent: `<root>/<agent_id>.json`, `model_dump_json(indent=2)`.
- Store root is a constructor argument; no production code chooses it.
- Writes atomic: tmp file plus `os.replace`, tmp removed on failure.
- Best-effort throughout: save and load failures log, never raise.
- `load` returns None on a missing or corrupt file.
- `list_ids` validates every `*.json` in the root.

## CheckpointDriver

- Wraps a driver callable `driver(agent) -> str | None`; saves checkpoints around driver turns.
- Before-save runs on turn 1 and every `interval` turns; default interval 1 saves every turn.
- After-save always runs.
- Driver raise: saves the failure state, then re-raises — containment still sees the failure.
- Counters and notes reload from the store on first sight of an agent id.
- That reload is the fresh-process resume path.
- `extra` records the wrapped driver class name.

## Wiring status

- `CheckpointDriver` is NOT attached in `build_runtime` (`wiring.py`).
- Nothing under `src/` constructs store or driver; tests and operators do.
- `/resume <agent_id>` reads `runtime.checkpoint_store` via `getattr` (`ui/terminal.py`).
- `build_runtime` never sets `checkpoint_store`; a wired runtime answers `no checkpoint for <id>`.
- `/resume` prints the checkpoint JSON — display only, restores nothing.

## What these are not

- Pump per-step snapshots serve containment — step timeout rolls the workspace back (`INFO-062`).
- Neither mechanism here serves that rollback.
- Agent side resumes agent context in-process; operator side resumes turn counters across processes.

## Owns
- The resumability model: the two checkpoint mechanisms, what each snapshots and resumes, where each lives, wiring status.

## Excludes
- Per-step snapshot rollback on timeout — `INFO-062`.
- Pump contract and fabrication kit contract — `INFO-037`.
- Module layout — `INFO-055`.
- The two-mechanism split ruling — `PD-002`.
- Entry-point commands like `/resume` — `INFO-070`.
