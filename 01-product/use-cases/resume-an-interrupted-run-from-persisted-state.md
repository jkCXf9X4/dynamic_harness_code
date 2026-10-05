---
id: INFO-024
type: info
title: Resume an interrupted run from persisted state
summary: A dead runtime process loses every running hierarchy; candidate: per-agent checkpoints and a resume that rebuilds the run from persisted state
date: 2026-10-05
status: draft
---

# Resume an interrupted run from persisted state

- The pain: a runtime process death — crash, OOM, host shutdown — loses every running hierarchy, because parent liveness is in-process (`INFO-014`) and nothing committed rebuilds the run.
- What already survives: artifacts and every action's code persist immutably (`INFO-006`, `INFO-002`), so results are on disk — but there is no committed way to reassemble a run from them.
- The candidate: auto-persist a per-agent checkpoint each committed turn; a resume rebuilds the hierarchy from those checkpoints and continues; recovery reuses partial on-disk results instead of redoing finished work.
- Scope note: distinct from crash containment (`INFO-005`) — containment surfaces a failed child to its parent, while resume restarts a dead run.

## Owns
- The run-level resumability candidate: checkpoints plus a rebuild-and-continue resume.

## Excludes
- Crash containment for a failed child — `INFO-005`.
- Artifact persistence the resume leans on — `INFO-006`.
- LLM-call failure handling — `INFO-020`.
