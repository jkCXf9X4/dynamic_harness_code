# Verb inventory — discussion material for INFO-029

Initial list of the surface's function calls, from
`give-agents-an-in-code-capability-surface.example.py`. One convention
throughout: a free verb takes the value acted on as its first argument —
`spawn`'s first argument is the parent whose child is created;
`publish`/`tool`/`ask_operator`/`fail` take the acting agent;
`request`/`post`/`search` take the handle. The library extends by new verbs,
never by method changes.

## Async agent interaction

| verb | signature | returns | fulfills | notes |
|---|---|---|---|---|
| `spawn` | `spawn(parent, spec, requirement=..., acceptance=..., channels=None, role=None)` | child handle | `INFO-004`, `INFO-009`, `INFO-010`, `INFO-018`, `INFO-019` | parenthood = first arg; `spec` = what the agent IS; `role=` is the role message |
| `result` | `result(child)` | result object (`.ok`, `.reason`, `.artifacts`) | `INFO-014`, `INFO-005`, `INFO-009` | blocks until the child settles; timeout unpinned |
| `request` | `request(peer, payload, timeout=...)` | reply | `INFO-015`, `INFO-012` | an artifact id as payload composes |
| `post` | `post(room, msg)` | — | `INFO-016` | many-to-many |
| `ask_operator` | `ask_operator(agent, question)` | answer | `INFO-023`, `INFO-017` | routes up the parent chain; the one carve-out |
| `fail` | `fail(agent, reason)` | — (turn ends as failed result) | `INFO-011` | sync; terminates the turn |

## Sync tools and artifacts

| verb | signature | returns | fulfills | notes |
|---|---|---|---|---|
| `tool` | `tool(agent, name, *args)` | tool handle | `INFO-006`, `INFO-002` | tool calls are publishes: full output persisted, handle returned |
| `search` | `search(out, query, limit=...)` | ranked hits | pagination | the "not the full output" rule |
| `lines` | `lines(out, offset, size)` | windowed read | pagination | |
| `read` | `read(out, size)` | capped pull | pagination | |
| `publish` | `publish(agent, headline=..., summary=..., report=...)` | artifact handle | `INFO-006`, `INFO-001` | headline → summary → report tiers |
| `artifact` | `artifact(agent, id)` | pulled handle | `INFO-012`, `INFO-006` | |
| `load_tool` | `load_tool(agent, id)` | callable | `INFO-007` | tools arrive as artifacts, not built-ins |
| `room` | `room(agent, name)` | room handle | `INFO-016`, `INFO-018` | lookup-or-create — unpinned |
| `agent` | `agent(agent, id)` | peer handle | `INFO-015`, `INFO-018` | resolves only visible agents — default group isolation |

## Data, not verbs

- Injected context: `self.id`, `self.requirement`, `self.acceptance`, `self.channels` (access name unpinned) — `INFO-003`, `INFO-018`.
- Handle attributes: `child.state`; `r.ok` / `r.reason` / `r.artifacts`; `art.id` / `art.headline` / `art.summary` / `art.report`; `out.id`.
- Agent kinds: spec values, e.g. `Worker = Agent()`, `Verifier = Agent()` — the harness ships none (`INFO-007`).

## Open points

- Sibling-peer wiring vocabulary: how peer links between siblings are expressed (turn 4's pipeline used a room as the wiring substrate).
- `self.channels` access name; `room(name)` lookup-or-create semantics.
- Namespace hygiene: flat verbs (`read`, `request`, `post`) are collision-prone; `from dhc import *` is illustrative.
- First-turn gating: children spawned inside one action start after the action settles — what makes `INFO-019`'s wording literal.
- `result(child, timeout=?)` unpinned; whether a kind carries a default role.
