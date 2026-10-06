---
title: Peer exchange
summary: Agents exchange work directly — sibling handoffs, direct messages, and shared rooms
---

# Peer exchange

Use cases between agents at the same level, with no parent mediating the
exchange.

## Owns
- Agent-to-agent behaviors outside a delegation edge.

## Excludes
- Parent-mediated coordination — `delegation/`.
- The artifact contract the handoffs rely on — `artifacts/`.

## Contents

<!-- pb:index:start -->
- **INFO-012** [Hand off artifacts between siblings](hand-off-artifacts-between-siblings.md) — A sibling passes its published artifact directly to another sibling as input, without routing through the parent
- **INFO-015** [Message another agent directly](message-another-agent-directly.md) — Any two agents can open a direct channel by identity and exchange request-reply traffic without a parent mediating
- **INFO-016** [Meet in a shared room](meet-in-a-shared-room.md) — Agents join a shared room where every posted message is visible to all members and any member can reply
<!-- pb:index:end -->
