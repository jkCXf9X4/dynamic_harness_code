---
id: INFO-025
type: info
title: Embed the runtime in a host process behind an API
summary: A host application can construct and drive the runtime through a committed API surface, decoupling the harness from any UI
date: 2026-10-05
status: draft
---

# Embed the runtime in a host process behind an API

- The pain: today the runtime is reachable only through the operator door (`INFO-017`); a host application — UI, service, CI job — cannot construct or drive it programmatically.
- The candidate: a committed API surface — construct a runtime, run a task, subscribe to outcome events — promised to integrators, so a strong API decouples the harness from any UI.
- Distinct from agent-developed extensibility (`INFO-007`): that is agents adding capabilities from inside; this is a host embedding the runtime from outside.

## Owns
- The embedding candidate: the host-facing API surface and its outcome stream.

## Excludes
- Agent-developed tools — `INFO-007`.
- The operator-to-root door — `INFO-017`.
- Container hosting of the runtime — `INFO-008`.
