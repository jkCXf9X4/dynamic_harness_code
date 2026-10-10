---
id: INFO-027
type: info
title: Trace a failure to its provenance without re-running
summary: A queryable event trail ties each agent to its actions and artifacts, so a failure is diagnosed by reading records only
date: 2026-10-05
status: draft
---

# Trace a failure to its provenance without re-running

## The gap

- **Pain**
  - Run fails: triage today re-derives what happened by re-executing.
  - No queryable cross-run record ties agent, action, result.
- **What survives**
  - Every action's code and results persist as immutable artifacts (`INFO-002`, `INFO-006`).
  - Raw material for provenance exists.
  - Not queryable as trail.

## The candidate

- **Queryable provenance trail**
  - Which agent produced which artifact from which delegation.
  - Failure diagnosed by reading records only.

## The design

- **Boundary event log**
  - Five event kinds carry causal ids (`INFO-049`).
  - Concurrent work reconstructs as DAG, not sequence.
- **By-reference payloads**
  - Trail carries content hashes and artifact references, never payload itself (`INFO-006`).
- **Boundary-only instrumentation**
  - Trace records what crossed boundary, never internals of executed code.
  - Operations, assignments, filesystem and network accesses stay untraced unless part of emitted output.
  - Action space stays unconstrained. Trace stays manageable.
- **Typed terminal states**
  - Completed, failed, cancelled, timeout (`INFO-005`, `INFO-032`, `INFO-034`).
  - Failures first-class outcomes, not generic errors.

## Notes

- Full analysis: `commit-to-a-minimal-execution-core-contract` sidecar, attached to `INFO-037`.
- Evidence from practice: immutable records make failure analysis read-only query.

## Owns
- Provenance-trail candidate: queryable run trace for failure triage without re-running.

## Excludes
- Event-log data model: vocabulary, causal ids, by-reference payloads — `INFO-049`.
- Artifact persistence — `INFO-006`.
- Action persistence — `INFO-002`.
- Crash surfacing — `INFO-005`.
- Context-rot surfacing — `INFO-021`.
