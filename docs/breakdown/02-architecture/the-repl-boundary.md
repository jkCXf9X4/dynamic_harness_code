---
id: INFO-072
type: info
title: The REPL boundary
summary: The hard interface between framework and agent-authored code — declared agent surface (facade, handles), snapshot crossings (events, rooms, context), log-first settlement gate, enforcement suite
date: 2026-10-12
status: current
---

# The REPL boundary

The contract on every object that crosses from framework into agent-authored code.

## The contract

- Declared-surface boundary, not a sandbox: blocks run arbitrary Python with import rights (`INFO-002`). Reach-around introspection stays possible by design.
- The contract buys: agent-authored code has nothing to rely on beyond the declared surface, so the surface cannot silently grow; the gates stay framework-owned.
- `AgentSurface` protocol (runtime-checkable) declares the agent contract; `AGENT_SURFACE` frozenset lists its names (`framework/agent.py`).
- `tests/framework/test_repl_boundary.py` pins the contract: facade identity, `dir(agent)` equals `AGENT_SURFACE`, no machinery in namespace values, handle discipline, snapshot isolation, context purity, log-first settlement.

## The agent surface

- Blocks see a `WorkspaceAgent` facade as `agent`, never the raw `Agent`.
- The facade forwards identity reads, token/cost reads, actions, supervision — nothing else.
- No `_runtime`, no `_status`, no `_result`, no `record_usage` on the facade: runtime reference, settlement state, usage seam stay framework-side.
- `children` is a tuple copy; a block cannot forge or drop sibling ids.
- Every namespace action callable (`spawn`, `send`, `complete`, ...) is facade-bound; `__self__` is the facade.
- The raw `Agent` stays framework-side: pump, settle path, driver seam keep it.

## Handle discipline

- `spawn` returns an `AgentHandle` — the join surface: await, poll, cancel, status, result.
- `AgentHandle` has no `get()` unwrap; the raw `Agent` is reachable only framework-side via `Runtime.get`.

## Snapshot crossings

- `Runtime.events` and `Runtime.tool_events` return deep-copy events; payload mutation stays private to the reader.
- `room()` joins for real, returns a deep-copy `Room`; membership, history, posting gate stay RoomManager-owned.
- The fabrication `context` stores runtime and engine private; `as_dict()` is pure workspace data, no agent object.
- The digest therefore holds copies, never live stream events.

## The settlement gate

- `_settle` gates on the `CompletionLog` first — the log is the single source of truth (`INFO-046`).
- A forged terminal `_status` (reach-around past the facade) can neither suppress nor duplicate the real completion; first log entry wins.

## Deliberate crossings, out of contract

- `bash` and import rights — the CodeAct shape (`INFO-002`).
- `state["_driver"]` — the brain-swap seam (`INFO-064`).
- `MockDriver` and `driver_from_settings` in the namespace — spawn-time driver selection (`INFO-064`).
- The driver receives the raw `Agent` — runtime machinery, needs `record_usage` and the runtime reference (`INFO-064`, `INFO-051`).

## Owns
- What crosses from the framework into agent-authored code: the agent facade, handle discipline, snapshot crossings (events, rooms, context), the declared-surface contract, and the enforcement suite that pins them.

## Excludes
- The driver seam and its raw-agent exception — `INFO-064`.
- Event-stream resolution discipline — `INFO-048`; the agent-facing stream contract — `INFO-051`.
- At-most-once settlement semantics — `INFO-046`.
- The fabrication kit contract — `INFO-037`.
- One turn = one Python block — `INFO-002`.
