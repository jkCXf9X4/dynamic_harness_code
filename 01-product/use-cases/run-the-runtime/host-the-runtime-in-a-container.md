---
id: INFO-008
type: info
title: Host the runtime in a container
summary: An operator runs the dhc runtime inside Docker or Podman as the outer security boundary
date: 2026-10-05
status: current
---

# Host the runtime in a container

- The full dhc runtime runs inside Docker or Podman as the outer security and deployment boundary (`INFO-001`).
- Agents, artifacts, and sandboxes live inside that boundary; nothing escapes to the host.
- The operator configures the container; agents never touch the host.

## Owns
- The container-hosting security and deployment boundary.

## Excludes
- Per-action execution isolation, the inner boundary — `INFO-002`.
- Agent tool extensions hosted by the runtime — `INFO-007`.
