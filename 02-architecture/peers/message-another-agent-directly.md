---
id: INFO-015
type: info
title: Message another agent directly
summary: Any two agents can open a direct channel by identity and exchange request-reply traffic without a parent mediating
date: 2026-10-05
status: current
---

# Message another agent directly

- Any two agents can open a direct channel: the sender addresses the recipient by identity, sends a message, and receives a reply — no parent mediating the exchange (`INFO-004`).
- The channel is point-to-point: only the two parties see the traffic; no room and no third agent is involved.
- A message can carry an artifact ID as its payload, so direct messaging composes with the artifact contract (`INFO-006`).
- In a delegation tree this appears as a sibling handoff — the delegation-pattern instance of the same channel (`INFO-012`).

## Owns
- Direct agent-to-agent messaging: any agent can address any other by identity and exchange request-reply traffic without a parent mediating.

## Excludes
- The delegation-pipeline instance, sibling artifact handoff — `INFO-012`.
- Parent-mediated reporting, the default route — `INFO-006`.
- The shared-room channel, many-to-many — `INFO-016`.
