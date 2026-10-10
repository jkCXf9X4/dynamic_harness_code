---
id: INFO-015
type: info
title: Message another agent directly
summary: Any two agents can open a direct channel by identity and exchange request-reply traffic without a parent mediating
date: 2026-10-05
status: current
---

# Message another agent directly

- **Direct channel by identity**
  - Sender addresses recipient by identity.
  - Sends message, receives reply.
  - No parent mediating exchange (`INFO-004`).
- **Point-to-point**
  - Only two parties see traffic.
  - No room involved. No third agent involved.
- **Artifact ID payload**
  - Message can carry artifact ID as payload (`INFO-006`).
  - Direct messaging composes with artifact contract.
- **Delegation-tree instance**
  - In delegation tree appears as sibling handoff (`INFO-012`).
  - Delegation-pattern instance of same channel.
- **Boundary (`INFO-054`)**
  - Primitive spec and framework/tooling classification: `INFO-054` (decision `AD-009`).
  - Direct message reaches recipient's awareness: digest, recent context, `events` tool.
  - Inbox read-state view (unread counts, read marking): tooling composed on top.
  - Agent chooses whether to use it.

## Owns
- Direct agent-to-agent messaging: any agent can address any other by identity, exchange request-reply traffic without parent mediating.

## Excludes
- Delegation-pipeline instance, sibling artifact handoff — `INFO-012`.
- Parent-mediated reporting, default route — `INFO-006`.
- Shared-room channel, many-to-many — `INFO-016`.
- Primitive spec and framework/tooling classification — `INFO-054`.
