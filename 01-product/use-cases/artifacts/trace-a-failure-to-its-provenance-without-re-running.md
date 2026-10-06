---
id: INFO-027
type: info
title: Trace a failure to its provenance without re-running
summary: A queryable event trail — CALL, DELEGATE, COMPLETE, AWAIT, CALLBACK — tying each agent to its actions and artifacts, so a failure is diagnosed by reading records only
date: 2026-10-05
status: draft
---

# Trace a failure to its provenance without re-running

- The pain: when a run fails, triage today re-derives what happened by re-executing, because there is no queryable cross-run record tying agent → actions → results.
- What already survives: every action's code and results persist as immutable artifacts (`INFO-002`, `INFO-006`) — the raw material for provenance exists but is not queryable as a trail.
- The candidate: a queryable provenance trail — which agent produced which artifact from which delegation — so a failure is diagnosed by reading records only.
- The event vocabulary is concrete: CALL (input → output at the code boundary), DELEGATE (task → input), COMPLETE (task → output), AWAIT (task → synchronization point), CALLBACK (task → callback execution).
- Every event carries its causal ids — calls carry `call_id` and `parent_call_id`; delegations carry `task_id`, `parent_task_id`, and `parent_call_id` — so concurrent work reconstructs as a DAG, not a sequence.
- Large payloads are traced by reference: the trace records content hashes and artifact references for big inputs and outputs; the payload itself stays in the artifact store (`INFO-006`).
- Instrumentation is boundary-only: the trace records what crossed the boundary, never the internals of executed code — operations, assignments, filesystem and network accesses stay untraced unless they are part of an emitted output. The action space stays unconstrained while the trace stays manageable.
- Terminal states are typed — completed, failed, cancelled, timeout — so failures are first-class outcomes, not generic errors (`INFO-005`, `INFO-032`, `INFO-034`).
- Full analysis: `commit-to-a-minimal-execution-core-contract.analysis.md`, next to this leaf.
- Evidence from practice: immutable, greppable records make failure analysis a read-only query, and immutable artifacts are what make that possible (`INFO-006`).

## Owns
- The provenance-trail candidate: a queryable run trace for failure triage without re-running.

## Excludes
- Artifact persistence — `INFO-006`.
- Action persistence — `INFO-002`.
- Crash surfacing — `INFO-005`.
- Context-rot surfacing — `INFO-021`.
