---
id: INFO-012
type: info
title: Hand off artifacts between siblings
summary: A sibling passes its published artifact directly to another sibling as input, without routing through the parent
date: 2026-10-05
status: current
---

# Hand off artifacts between siblings

- A sibling passes its published artifact directly to another sibling as that sibling's input, without routing through the parent (`INFO-006`).
- The sending sibling addresses the artifact by its content hash, so the handoff is safe to repeat and to verify (`INFO-006`).
- The parent sees only the pipeline's final summary; intermediate hops stay invisible to it.
- The receiving sibling runs in its own contained thread, as any agent does (`INFO-005`).

## Owns
- Peer-to-peer, artifact-mediated message passing between siblings.

## Excludes
- Parent-mediated reporting, the default route — `INFO-006`.
- Static fan-out, which forbids child-to-child communication — `INFO-009`.
