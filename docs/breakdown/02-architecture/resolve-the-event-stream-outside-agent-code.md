---
id: INFO-048
type: info
title: Resolve the event stream outside agent code
summary: Runtime-owned resolution discipline — the turn engine settles each channel persist-before-execute, at most once, ensure-terminal; per AD-006 the stream's consumption moved into the loop (the agent reads its own stream) while the discipline stays runtime-owned
date: 2026-10-06
status: current
---

# Resolve the event stream outside agent code

- Resolution discipline is runtime-owned: the turn engine settles each channel persist-before-execute, at most once each, ensure-terminal per handle (`INFO-031`) — whichever consumer settles first wins (`INFO-046`).
- Per AD-006 (a partial reversal of this ruling), the stream's *consumption* moved into the loop: the agent's `__runner` reads its own stream as ordinary data as part of its orchestration. The *discipline* — FIFO order, at-most-once delivery, persist-before-execute — stays runtime-owned and unchanged, so a degrading agent cannot corrupt the stream or the boundary log (`INFO-049`).
- The stream's intake is typed to the terminal: only a frozen `Result` enters — one settled child = one `Event`, the `Result` tagged with its child (`INFO-039`) — no arbitrary payloads, no live handles.
- Every bus exposes a non-destructive `peek()` alongside the destructive `drain()` (`_MemoryBus`, `EventStream`, `_WiredBus`), and each consumer keeps its own cursor over the non-destructive stream: `Runtime.events` a per-agent cursor (consume-once semantics preserved), the caps watchdog a per-step delta, the StateWriter poll thread its own watermark (each event forwarded exactly once). The `completions:<id>` topics stay destructive (`INFO-046` at-most-once).
- The rejected shape — *resolution* inside the REPL — is the mockup's drain gesture: the queue in the interpreter becomes interpreter-level lock discipline, failing the fault-containment and private-namespace groups. Consumption in-loop is the accepted shape; resolution (the discipline) is not.

## Owns
- The event-stream resolution machinery: loop-side polling, typed intake, runtime-owned settlement discipline, and the registration mechanics behind handle-scoped registration.

## Excludes
- The event-stream contract as seen from agent code — `INFO-051`.
- The settlement pattern the resolution serves — `INFO-046`.
- The dispatch of settled completions between parent actions — `INFO-047`.
- The kernel commitment itself — the turn engine made real — `INFO-037`.
