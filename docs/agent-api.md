# Agent API — the in-block surface

<!-- GENERATED FILE — do not edit. Regenerate with python3 tools/generate_agent_api.py -->

Every name an agent's action block can call, generated from the surface registry (`src/dhc/framework/surface.py`) — the same single source of truth the prompt's API section is rendered from. The registry currently holds 47 entries: 29 core, 3 advanced, 15 internal.

- **core** — prompt-visible and in `list_tools()`: the vocabulary an agent is taught.
- **advanced** — in `list_tools()` but not prompt-visible: reachable, not advertised.
- **internal** — never advertised: injected machinery (the fabrication kit, the driver factory).

A tutorial that runs this surface end to end: [quickstart.md](quickstart.md).

## Core

### `Await`

```python
Await(handle)
```

Yield: park the runner until the child settles (await idiom 1). *(tier: core)*

Example:

```python
yield Await(handle)
```

### `Poll`

```python
Poll(handle)
```

Yield: check the child's status, then resume (await idiom 2). *(tier: core)*

Example:

```python
yield Poll(handle)
```

### `Sleep`

```python
Sleep(seconds)
```

Yield: pause the runner for a beat (stop-flag aware). *(tier: core)*

Example:

```python
yield Sleep(1.0)
```

### `ack`

```python
ack(escalation_id)
```

Acknowledge a child's escalation (closes the escalation loop). *(tier: core)*

Example:

```python
ack(escalation_id)
```

### `agent`

```python
agent
```

The agent facade: identity, accounting reads, actions. *(tier: core)*

Example:

```python
agent.status()
```

### `answers`

```python
answers(question_id)
```

Poll the operator's answers to your question (empty until answered). *(tier: core)*

Example:

```python
answers(question_id)
```

### `archive`

```python
archive(artifact_id)
```

Copy an artifact into the durable archive. *(tier: core)*

Example:

```python
archive(artifact_id)
```

### `ask_operator`

```python
ask_operator(question)
```

Ask the human operator a question; returns the question id. *(tier: core)*

Example:

```python
qid = ask_operator('which source?')
```

### `await_`

```python
await_(handle)
```

Block until the child settles; return its Completion. *(tier: core)*

Example:

```python
comp = await_(handle)
```

### `bash`

```python
bash(cmd)
```

Run a shell command; return the captured output as text. *(tier: core)*

Example:

```python
bash('ls -1')
```

### `children_of`

```python
children_of(handle)
```

Handles of the agent's spawned children. *(tier: core)*

Example:

```python
handles = children_of(handle)
```

### `complete`

```python
complete(headline, artifacts=())
```

Settle the agent as completed. *(tier: core)*

Example:

```python
complete('done', artifacts=[art.id])
```

### `escalate`

```python
escalate(requirement, reason)
```

Escalate to the parent: requirement + reason (two args). *(tier: core)*

Example:

```python
escalate('need human decision', 'blocked on approval')
```

### `fail`

```python
fail(reason)
```

Settle the agent as failed. *(tier: core)*

Example:

```python
fail('data source unavailable')
```

### `gather`

```python
gather(handles, return_failures=False)
```

Join spawned children and aggregate their Completions. *(tier: core)*

Example:

```python
comps = gather([c1, c2], return_failures=True)
```

### `list_artifacts`

```python
list_artifacts()
```

List the stored artifact ids. *(tier: core)*

Example:

```python
list_artifacts()
```

### `list_tools`

```python
list_tools()
```

List the installed tool names (core + advanced surface). *(tier: core)*

Example:

```python
list_tools()
```

### `poll`

```python
poll(handle)
```

The child's current status (non-blocking). *(tier: core)*

Example:

```python
poll(handle)
```

### `post`

```python
post(room_name, body)
```

Post a message to a room. *(tier: core)*

Example:

```python
post('research', 'finding posted')
```

### `publish`

```python
publish(headline, summary, report)
```

Persist a finding as a durable artifact. *(tier: core)*

Example:

```python
art = publish('headline', 'summary', 'report body')
```

### `read_artifact`

```python
read_artifact(artifact_id, level='summary')
```

Read an artifact (progressive disclosure: headline/summary/report; full and raw are aliases of report). *(tier: core)*

Example:

```python
read_artifact(artifact_id, level='summary')
```

### `record_result`

```python
record_result(reason)
```

Record a not-ok last result (does NOT cancel). *(tier: core)*

Example:

```python
record_result('tool returned empty')
```

### `result`

```python
result()
```

The agent's current result. *(tier: core)*

Example:

```python
result()
```

### `room`

```python
room(room_name)
```

Join (creating if needed) a shared room; return a snapshot. *(tier: core)*

Example:

```python
snapshot = room('research')
```

### `room_messages`

```python
room_messages(room_name)
```

Read a room's traffic in post order without joining. *(tier: core)*

Example:

```python
msgs = room_messages('research')
```

### `send`

```python
send(recipient_id, body)
```

Direct message to another agent (the core primitive). *(tier: core)*

Example:

```python
send(recipient_id, 'please proceed')
```

### `spawn`

```python
spawn(requirement, acceptance=(), driver=None, on_done=None)
```

Spawn a child agent (non-blocking); return its handle. *(tier: core)*

Example:

```python
handle = spawn('research the market')
```

### `status`

```python
status()
```

The agent's current status. *(tier: core)*

Example:

```python
status()
```

### `tool`

```python
tool(callable, *args)
```

Run a callable, capturing its output as a ToolResult. *(tier: core)*

Example:

```python
tool(len, [1, 2, 3])
```

## Advanced

Reachable, not advertised (visible via `list_tools()`):

- `channel_read` — Deprecated alias of room_messages (advanced).
- `events` — The agent's own settled events, consume-once.
- `messenger` — Per-agent facade: send + inbox/read-state sugar (advanced; prefer send).

## Internal

15 injected-machinery names, never advertised: `__runner`, `acceptance_met`, `build_prompt`, `caps`, `checkpoint`, `compact`, `context`, `decide`, `ensure_fabrication`, `observe`, `rollback`, `run_block`, `settle`, `settle_completed`, `state`.

---

<!-- registry-hash: f91db3e2d1805126 -->
