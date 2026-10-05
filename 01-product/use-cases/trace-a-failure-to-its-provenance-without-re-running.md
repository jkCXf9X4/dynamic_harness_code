---
id: INFO-027
type: info
title: Trace a failure to its provenance without re-running
summary: A queryable trail tying each agent to its actions and artifacts, so a failure is diagnosed by reading records only
date: 2026-10-05
status: draft
---

# Trace a failure to its provenance without re-running

- The pain: when a run fails, triage today re-derives what happened by re-executing, because there is no queryable cross-run record tying agent → actions → results.
- What already survives: every action's code and results persist as immutable artifacts (`INFO-002`, `INFO-006`) — the raw material for provenance exists but is not queryable as a trail.
- The candidate: a queryable provenance trail — which agent produced which artifact from which delegation — so a failure is diagnosed by reading records only.
- Evidence from practice: immutable, greppable records make failure analysis a read-only query, and immutable artifacts are what make that possible (`INFO-006`).

## Owns
- The provenance-trail candidate: a queryable run trace for failure triage without re-running.

## Excludes
- Artifact persistence — `INFO-006`.
- Action persistence — `INFO-002`.
- Crash surfacing — `INFO-005`.
- Context-rot surfacing — `INFO-021`.
