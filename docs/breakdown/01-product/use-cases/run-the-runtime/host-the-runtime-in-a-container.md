---
id: INFO-008
type: info
title: Host the runtime in a container
summary: An operator runs the dhc runtime inside Docker or Podman as the outer deployment boundary
date: 2026-10-05
status: current
---

# Host the runtime in a container

- The full dhc runtime runs inside Docker or Podman as the outer deployment boundary (`INFO-001`).
- **Deployment boundary, not a sandbox.**
  - The container is the outer boundary for the whole runtime.
  - The runtime provides no sandbox; agent code runs in-process.
- **Operator configures the container.**
  - Agents never touch the host.

## Owns
- The container-hosting deployment boundary.

## Excludes
- Per-action execution isolation, the inner boundary — `INFO-002`.
- Agent tool extensions hosted by the runtime — `INFO-007`.
- The configuration model the container deployment is configured through — `INFO-065`.
