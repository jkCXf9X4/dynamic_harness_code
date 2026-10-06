---
id: INFO-049
type: info
title: Boundary event log
summary: The provenance trail's data model — five boundary events with causal ids, payloads traced by reference, greppable records
date: 2026-10-06
status: current
---

# Boundary event log

- The event vocabulary is concrete: CALL (input → output at the code boundary), DELEGATE (task → input), COMPLETE (task → output), AWAIT (task → synchronization point), CALLBACK (task → callback execution).
- Every event carries its causal ids — calls carry `call_id` and `parent_call_id`; delegations carry `task_id`, `parent_task_id`, and `parent_call_id` — so concurrent work reconstructs as a DAG, not a sequence (`INFO-027`).
- Large payloads are traced by reference: the log records content hashes and artifact references for big inputs and outputs; the payload itself stays in the artifact store (`INFO-006`).
- The log is greppable text — records readable with plain tools.

## Owns
- The boundary event log's data model: the event vocabulary, causal ids, by-reference payloads, and text serialization.

## Excludes
- The provenance-trail capability this log serves — `INFO-027`.
- The artifact store holding the referenced payloads — `INFO-006`.
- The kernel that emits the events — `INFO-037`.
