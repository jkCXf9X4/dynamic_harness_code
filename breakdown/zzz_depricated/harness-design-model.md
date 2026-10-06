### DEPRICATED ###

---
id: INFO-042
type: info
title: Harness design model
summary: The harness runs the code runtime as a black box — traceability attaches at the call-code and delegation boundaries only — giving the agent a highly expressive action space with observable, attributable boundaries
date: 2026-10-06
status: draft
---

# Harness design model

> Incorporated 2026-10-06 from the harness use-case source analysis (`INFO-037`) — the design model is organizing design, not a use case.

The harness exposes a stateful computational environment to the agent.

The agent has access to:

* `call-code` — execute arbitrary code in a persistent REPL.
* `delegate` — start asynchronous child-agent work.
* `await` — wait for a child to complete.
* `status` — inspect a child without waiting.
* `on_done` — register a callback for child completion.

The harness treats the code runtime as a **black box**.

Traceability is provided at the `call-code` and delegation boundaries rather than by instrumenting the code executed inside the REPL.

The core principle is:

> Give the agent a highly expressive action space while making the boundaries between agent, execution, and child work observable and attributable.

## Owns
- The design model for how the harness runs the code runtime: black-box execution, boundary-only traceability, and the core principle.

## Excludes
- The recommended minimal contract that model supports — `INFO-043`.
- The commitment to it — `INFO-037`.
