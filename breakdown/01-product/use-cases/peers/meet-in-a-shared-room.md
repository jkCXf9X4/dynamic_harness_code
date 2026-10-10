---
id: INFO-016
type: info
title: Meet in a shared room
summary: Agents join a shared room where every posted message is visible to all members and any member can reply
date: 2026-10-05
status: current
---

# Meet in a shared room

- **Room is the medium**
  - Agents join common room.
  - Every posted message visible to all members.
  - Not any pair's channel.
- **Many-to-many posting**
  - Agent posts update, question, or artifact ID.
  - Any other member, not fixed recipient, can pick up and reply (`INFO-006`).
- **Visible membership**
  - Agent sees who else is in room.
  - Thread can pull in participants ad hoc.
- **Traffic persists**
  - Room traffic persists for room's lifetime.
  - Agent joining late catches up on what it missed.
- **Complements direct messaging**
  - Broadcast to group when audience is "whoever can help".
  - Point-to-point when one agent (`INFO-015`).
- **Boundary (decision `AD-009`)**
  - Rooms are composed *policy*, not framework machinery.
  - Tooling over core directed-message primitive.
  - Removable without changing what core guarantees.
  - Agent keeps full control of which communication patterns its stack carries.

## Owns
- Meeting-room channel: shared space agents join, post to, read from, visible to every member.

## Excludes
- Direct point-to-point messaging — `INFO-015`.
- Pull-based artifact consumption, delivering content on demand without a room — `INFO-006`.
- Broadcast of one requirement to spawned children, a delegation pattern — `INFO-013`.
