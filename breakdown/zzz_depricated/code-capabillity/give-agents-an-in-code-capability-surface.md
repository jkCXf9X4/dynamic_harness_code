---
### DEPRICATED ###

id: INFO-029
type: info
title: Give agents an in-code capability surface
summary: Agents act through one injected self object — async agent interaction, sync tool calls that return paginated artifact handles — so every use case is fulfilled by a call
date: 2026-10-05
status: draft
---

# Give agents an in-code capability surface

- The pain: the action loop (`INFO-001`) commits every turn to emitting one Python block (`INFO-002`), but nothing defines what that block can call — each use case (`INFO-004`, `INFO-006`, `INFO-014`, `INFO-015`) implies a capability without a committed call contract to fulfill it.
- The candidate: an injected `self` carrying read-only task context (`id`, `requirement`, `acceptance`, `channels`), plus a library of free verbs taking the value acted on as their first argument — async agent interaction (`spawn(self, ...)`, `result(child)`, `request(peer)`, `ask_operator(self)`), sync tool calls returning paginated artifact handles (`tool(self, ...)`, `search(out)`, `lines(out)`, `read(out)`), and artifact and channel primitives (`publish`, `artifact`, `load_tool`, `room`, `post`, `fail`).
- Four mechanics carry it: tool calls are publishes (full output persists as a content-addressed artifact, `INFO-006`); handles are transferable values (how `INFO-019` hands live children and `INFO-012` composes); the sync/async split separates the two blocking classes — agent interaction awaits (liveness `INFO-014`, mid-turn steering `INFO-022`), tool calls block briefly and never interleave; spawn takes a spec value plus task args, so agent kinds and spawn helpers are constructed values — the extension point this candidate exists to provide (`INFO-007`).
- Every operation is a free verb taking the value acted on as its first argument (`spawn(parent, ...)`, `tool(self, ...)`, `request(peer, ...)`) — the library extends by new verbs, never by method changes, and the injected `self` carries no behavior.
- The verb inventory as discussion material: `give-agents-an-in-code-capability-surface.verbs.md`, next to this leaf.
- A reviewable example of the surface: `give-agents-an-in-code-capability-surface.example.py`, next to this leaf — now including multi-level setup (`INFO-018`, `INFO-019`).

## Owns
- The agent-facing capability surface: the injected object and the call contract every use case is expressed through.

## Excludes
- The per-turn action loop that persists and executes the block — `INFO-002`.
- The artifact store and headline→summary→report tiers the handles resolve against — `INFO-006`.
- Crash containment and failure surfacing, which stay runtime-side — `INFO-005`, `INFO-020`.
- The container boundary the blocks execute inside — `INFO-008`.
