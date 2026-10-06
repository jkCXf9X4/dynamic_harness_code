---
id: INFO-048
type: info
title: Resolve the event stream outside agent code
summary: Runtime-owned resolution machinery — the general event loop polls registered streams outside agent action code, and the turn engine settles each channel persist-before-execute, at most once, ensure-terminal
date: 2026-10-06
status: current
---

# Resolve the event stream outside agent code

- Resolution is runtime-owned: the turn engine settles each channel outside agent action code — persist-before-execute, at most once each, ensure-terminal per handle (`INFO-031`) — whichever consumer settles first wins (`INFO-046`).
- The general event loop polls every registered stream outside agent action code, and only what is registered; no stream surface reaches agent code — `agent.events` is never polled from the REPL (`INFO-045`).
- The stream's intake is typed to the terminal: only a frozen `Result` enters — one settled child = one `Event`, the `Result` tagged with its child (`INFO-039`) — no arbitrary payloads, no live handles.
- The rejected shape — resolution inside the REPL — is the mockup's drain gesture: the queue in the interpreter becomes interpreter-level lock discipline, failing the fault-containment and private-namespace groups.

## Owns
- The event-stream resolution machinery: loop-side polling, typed intake, runtime-owned settlement discipline, and the registration mechanics behind handle-scoped registration.

## Excludes
- The boundary contract as seen from agent code — `INFO-045`.
- The settlement pattern the resolution serves — `INFO-046`.
- The dispatch of settled completions between parent actions — `INFO-047`.
- The kernel commitment itself — the turn engine made real — stays with the execution-core contract, uncommitted: `INFO-037`.
