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

- The pain: when a run fails, triage today re-derives what happened by re-executing, because there is no queryable cross-run record tying agent → actions → results.
- What already survives: every action's code and results persist as immutable artifacts (`INFO-002`, `INFO-006`) — the raw material for provenance exists but is not queryable as a trail.

## The candidate

- A queryable provenance trail — which agent produced which artifact from which delegation — so a failure is diagnosed by reading records only.

## The design

- The trail is a boundary event log: five event kinds carrying causal ids, so concurrent work reconstructs as a DAG, not a sequence (`INFO-049`).
- Large payloads are traced by reference — the trail carries content hashes and artifact references, never the payload itself (`INFO-006`).
- Instrumentation is boundary-only: the trace records what crossed the boundary, never the internals of executed code — operations, assignments, filesystem and network accesses stay untraced unless they are part of an emitted output. The action space stays unconstrained while the trace stays manageable.
- Terminal states are typed — completed, failed, cancelled, timeout — so failures are first-class outcomes, not generic errors (`INFO-005`, `INFO-032`, `INFO-034`).

## Notes

- Full analysis: the `commit-to-a-minimal-execution-core-contract` sidecar, attached to `INFO-037`.
- Evidence from practice: immutable records make failure analysis a read-only query.

## Owns
- The provenance-trail candidate: a queryable run trace for failure triage without re-running.

## Excludes
- The event-log data model — vocabulary, causal ids, by-reference payloads — `INFO-049`.
- Artifact persistence — `INFO-006`.
- Action persistence — `INFO-002`.
- Crash surfacing — `INFO-005`.
- Context-rot surfacing — `INFO-021`.
