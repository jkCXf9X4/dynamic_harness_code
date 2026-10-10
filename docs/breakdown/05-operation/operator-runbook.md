---
id: INFO-071
type: info
title: Operator runbook
summary: Where run output lands and how to read it — state files, the boundary event log, artifact layout, chat context files, and resume
date: 2026-10-10
status: current
---

# Operator runbook

Where run output lands and how to read it. Defaults below; `DHC_WORKSPACE_ROOT` and `DHC_ARTIFACT_ROOT` move them.

## Run root

- Run root is the artifact root's parent (`src/dhc/ui/state.py`).
- Default artifact root: `<workspace_root>/.dynamic-harness/artifacts` (`src/dhc/data/config.py`).
- Workspace root defaults to the current directory.
- Default run root: `./.dynamic-harness`.
- The value demo overrides the artifact root with a tempdir; its report path is fixed (`INFO-057`).

## State files

- `StateWriter` writes four files into the run root (`src/dhc/ui/state.py`).
  - `agent_tree.json` — JSON array of root nodes, recursive `children`.
  - `stats.json` — aggregate counters over the tree.
  - `agents.txt` — box-drawn text tree.
  - `events.jsonl` — append-only, one JSON line per event.
- What the views contain: `INFO-059`.
- `snapshot()` rewrites `agent_tree.json`, `stats.json`, `agents.txt`.
- Activity events throttle snapshots to once per `snapshot_interval`; default 5.0 s.
- Terminal events force a snapshot plus one dedicated `events.jsonl` record.
- `events.jsonl` never truncates.
- The terminal forces a snapshot after each requirement and touches `events.jsonl` when absent.
- `/events` tails the last 20 lines of `events.jsonl` (`INFO-070`).

## Boundary event log

- `boundary-events.jsonl` sits in the artifact root, append-only (`src/dhc/tooling/artifact_store.py`).
- One JSON object per line: `kind`, `causal_id`, `agent_id`, `payload`, `ts`.
- `read(agent_id, kind)` filters; events return in append order, oldest first.
- Data model: `INFO-049`.

## Artifacts

- Artifact root layout: `index.json` plus `artifacts/<id>.json`.
- `index.json` maps each id to headline and summary.
- `artifacts/<id>.json` holds the full report body.
- Ids are content addresses: sha256 over the full body.
- Identical content stores once; `put` returns the existing id.
- Index writes are atomic: temp file plus rename; the index reloads on reopen.
- Stored artifacts never mutate.
- Tier semantics: `INFO-006`.

## Chat context files

- The chat command persists `.dhc/context.md` plus `.dhc/transcript.md` under the workspace root (`INFO-070`).

## Resume

- `/resume <agent_id>` prints the agent's persisted checkpoint (`INFO-070`).
- Checkpoints load from `CheckpointStore` (`src/dhc/ui/checkpoint.py`): one `<agent_id>.json` per agent.
- `build_runtime` attaches no `runtime.checkpoint_store`, so `/resume` finds nothing until an operator attaches one.
- Checkpoint model: `INFO-063`.

## Owns
- Where run output lands and how to read it: run root, state files, boundary log, artifact layout, chat context files, resume.

## Excludes
- Quick start: `INFO-057`.
- State view-model contents: `INFO-059`.
- Boundary log data model: `INFO-049`.
- Artifact tier semantics: `INFO-006`.
- The two entry points: `INFO-070`.
- Checkpoint model: `INFO-063`.
