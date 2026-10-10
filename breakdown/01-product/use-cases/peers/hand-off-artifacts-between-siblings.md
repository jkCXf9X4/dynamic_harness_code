---
id: INFO-012
type: info
title: Hand off artifacts between siblings
summary: A sibling passes its published artifact directly to another sibling as input, without routing through the parent
date: 2026-10-05
status: current
---

# Hand off artifacts between siblings

- **Direct sibling handoff**
  - Sibling passes published artifact directly to another sibling as input (`INFO-006`).
  - No routing through parent.
- **Content-hash addressing**
  - Sending sibling addresses artifact by content hash (`INFO-006`).
  - Handoff safe to repeat and to verify.
- **Parent visibility**
  - Parent sees only pipeline's final summary.
  - Intermediate hops stay invisible to it.
- Receiving sibling contained, as any agent is (`INFO-005`).

## Owns
- Peer-to-peer, artifact-mediated message passing between siblings.

## Excludes
- Parent-mediated reporting, default route — `INFO-006`.
- Static fan-out, which forbids child-to-child communication — `INFO-009`.
