---
id: INFO-025
type: info
title: Embed the runtime in a host process behind an API
summary: A host application can construct and drive the runtime through a committed API surface, decoupling the harness from any UI
date: 2026-10-05
status: draft
---

# Embed the runtime in a host process behind an API

- **Pain**
  - Runtime reachable today only through operator door (`INFO-017`).
  - Host application (UI, service, CI job) cannot construct or drive it programmatically.
- **Candidate**
  - Committed API surface: construct runtime, run task, subscribe to outcome events.
  - Promised to integrators.
  - Strong API decouples harness from any UI.
- **Distinct from agent-developed extensibility**
  - Agent-developed extensibility (`INFO-007`): agents adding capabilities from inside.
  - This: host embedding runtime from outside.

## Owns
- Embedding candidate: host-facing API surface and its outcome stream.

## Excludes
- Agent-developed tools — `INFO-007`.
- Operator-to-root door — `INFO-017`.
- Container hosting of runtime — `INFO-008`.
