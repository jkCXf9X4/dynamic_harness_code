---
id: INFO-049
type: info
title: Boundary event log
summary: The provenance trail's data model — five boundary events with causal ids, payloads traced by reference, greppable records
date: 2026-10-07
status: current
---

# Boundary event log

- The boundary event log persists every boundary crossing as one greppable JSON-lines record under `artifact_root/boundary-events.jsonl` (`INFO-049`).
- Five event kinds exist: `spawned`, `settled`, `cancelled`, `published`, and `messaged`; an unknown kind raises on append.
- Each line carries `kind`, `causal_id`, `agent_id`, `payload`, and `ts`; `payload` holds only ids by reference (artifact ids, child ids), never full bodies.
- `causal_id` links an event to the event that caused it — a `settled`/`published` record references the `spawned` record's id — so concurrent work reconstructs as a DAG.
- The log is append-only, thread-safe, and survives reopen; `read(agent_id, kind)` filters the trail without a separate index.
- The wired `_BoundarySink` maps the runtime's event kinds onto the five boundary kinds (boundary events only; `turn_*`, `crash`, and escalation events are not boundary crossings).

## Owns
- The boundary event log's contract: the five event kinds, causal linking by id, append-only JSON-lines records under the artifact root.

## Excludes
- Content-addressed artifact storage — `INFO-006`.
- Stream resolution and the at-most-once/persist-before-execute discipline — `INFO-048`.
- The runtime-owned completion dispatch that carries settled outcomes — `INFO-047`.