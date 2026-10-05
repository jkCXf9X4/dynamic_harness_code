---
id: INFO-016
type: info
title: Meet in a shared room
summary: Agents join a shared room where every posted message is visible to all members and any member can reply
date: 2026-10-05
status: current
---

# Meet in a shared room

- Agents join a common room where every posted message is visible to all members; the room is the medium, not any pair's channel.
- Posting is many-to-many: an agent posts an update, a question, or an artifact ID, and any other member — not a fixed recipient — can pick it up and reply (`INFO-006`).
- Membership is visible: an agent can see who else is in the room, so a thread can pull in participants ad hoc.
- Room traffic persists for the room's lifetime, so an agent joining late can catch up on what it missed.
- The room complements direct messaging: broadcast to the group when the audience is "whoever can help", point-to-point when it is one agent (`INFO-015`).

## Owns
- The meeting-room channel: a shared space agents join, post to, and read from, visible to every member.

## Excludes
- Direct point-to-point messaging — `INFO-015`.
- Pull-based artifact consumption, which delivers content on demand without a room — `INFO-006`.
- Broadcast of one requirement to spawned children, a delegation pattern — `INFO-013`.
