---
id: INFO-045
type: info
title: Resolve the event stream outside run_code
summary: The stream's intake is typed to the terminal — one settled child = one Event, a frozen Result — and the general event loop resolves it outside run_code; the REPL receives settled values and never drains or polls the stream
date: 2026-10-06
status: current
---

# Resolve the event stream outside run_code

- The stream's intake is typed to the terminal: only a `Result` enters — one settled child = one `Event`, the frozen `Result` tagged with its child (`INFO-039`) — no arbitrary payloads, no live handles.
- Resolution is runtime-owned: the turn engine settles the channel outside `run_code` — persist-before-execute, at most once each, ensure-terminal per handle (`INFO-031`) — and dispatches between the parent's own actions (`INFO-039`).
- The REPL never drains the stream: it receives settled values as data between its own actions, and the callback executes in the parent's REPL, never concurrently (`INFO-033`, `INFO-046`).
- The general event loop polls every registered stream outside `run_code`; `agent.events` is never polled from the REPL — the REPL-side pull primitives, await and poll (`INFO-031`, `INFO-032`), act on child handles, never on the stream.
- Registration is by held handle: an agent registers its own stream, a child's via its spawn handle, or a peer's only via a wired channel (`INFO-018`) — the loop polls what is registered, nothing more.
- The rejected shape — resolution inside the REPL — is the mockup's drain gesture: the queue in the interpreter becomes interpreter-level lock discipline, failing the fault-containment and private-namespace groups.

## Owns
- The event stream's boundary contract: typed intake (`Result` only), runtime-owned resolution — never resolved inside `run_code` (`EVAL-001`), loop-side polling (`agent.events` never polled from the REPL), and handle-scoped registration.

## Excludes
- Where settled events execute — the parent's own REPL, never concurrently — `INFO-033`.
- The settlement pattern this resolution serves — `INFO-046`.
- The boundary log watching the stream from outside — `INFO-027`.
- The kernel commitment itself — the turn engine made real — stays with the execution-core contract, uncommitted.
