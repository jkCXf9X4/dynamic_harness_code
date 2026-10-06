---
id: INFO-035
type: info
title: Keep an output history distinct from REPL state
summary: Explicitly returned outputs are retained as a queryable history, separate from the agent's working variables
date: 2026-10-06
status: current
---

# Keep an output history distinct from REPL state

- Each action's returned output is retained in an output history the agent can inspect later — the agent can recover information it previously generated without re-running it.
- Output history is separate from REPL state: only explicitly returned or emitted results enter the history; ordinary variable assignments stay private workspace state (`INFO-030`).
- This keeps externally meaningful output — what crossed the boundary — distinct from internal working state.

## Owns
- The output-history contract: what enters it, how it is retained, and how it is inspected.

## Excludes
- The REPL workspace state itself — `INFO-030`.
- The provenance trail's record of boundary crossings — `INFO-027`.
