# Quickstart — a full session in fifteen minutes

This tutorial runs a complete agent session: build a runtime, spawn a root
agent, fan out children, await them, read artifacts, inspect events. It uses
the mock driver — no API key, no network. Every code block below is executed
by CI (`tests/docs/test_quickstart_docs.py`), so it cannot drift from the
code.

The same pattern drives `tests/test_integration.py` and
`examples/value_demo.py`.

## 0. Install

```bash
pip install -e .
```

## 1. Build a runtime

`build_runtime` wires the real modules — engine, event bus, artifact store,
channels — over a fresh artifact root:

```python
import tempfile
from pathlib import Path

from dhc import build_runtime

artifact_root = Path(tempfile.mkdtemp(prefix="dhc-quickstart-"))
runtime = build_runtime(mock=True, artifact_root=artifact_root)
runtime.start()
```

`mock=True` selects the deterministic driver path, so the tutorial runs
offline.

## 2. Spawn a root agent

An agent is spawned with a *requirement* (its unit of work) and a *driver*
that produces its coded actions. `MockDriver` returns scripted code blocks,
then settles the agent. First the script each child runs — publish a
finding, then complete:

```python
CHILD = (
    "art = publish('child finding', 'child summary', 'child report body')\n"
    "result = complete('child done', artifacts=[art.id])"
)
```

Now the root. Its first turn fans out two children; its second turn gathers
them, aggregates their artifacts, and settles. The child script is inlined
with `%r` so each block is self-contained — an agent's namespace holds the
in-code surface, not this script's globals:

```python
from dhc import MockDriver

root = runtime.spawn(
    "Research the AI-agent market",
    driver=MockDriver([
        # Turn 1: fan out — spawn two children, then settle the turn.
        "c1 = spawn('market size', driver=MockDriver.single(%r))\n"
        "c2 = spawn('competitors', driver=MockDriver.single(%r))\n"
        "result = complete('spawned 2 children')" % (CHILD, CHILD),
        # Turn 2: gather the children, aggregate, settle.
        "comps = gather([c1, c2], return_failures=True)\n"
        "ids = [c.artifact_ids[0] for c in comps"
        " if c.status.value == 'completed']\n"
        "final = publish('final report', 'aggregated findings',"
        " {'artifact_ids': ids})\n"
        "result = complete('root done', artifacts=[final.id])",
    ]),
)
```

The code inside `MockDriver([...])` is what an *agent's* action block looks
like: `spawn` is non-blocking, `gather` joins children, `publish` persists a
finding, `complete` settles the agent. With a real LLM the driver writes
these blocks itself; the surface is identical.

## 3. Await the root

`await_` blocks until the agent settles and returns its `Completion`:

```python
completion = runtime.await_(root.id)
print(completion.status.value)   # completed
print(completion.summary)        # root done
print(completion.artifact_ids)  # ['sha256:...']
```

## 4. Read artifacts

Artifacts are content-addressed and read through progressive disclosure —
headline first, summary next, full report only when needed:

```python
final_id = completion.artifact_ids[0]
print(runtime.artifact_store.get_headline(final_id))  # final report
print(runtime.artifact_store.get_summary(final_id))   # aggregated findings
```

Inside an action block the same read is `read_artifact(artifact_id, level=...)`
with levels `headline`, `summary`, `report` (plus `full`/`raw` aliases).

## 5. Inspect events

The boundary log records what crossed agent boundaries — spawns, settlements,
publishes — with causal ids:

```python
for event in runtime.boundary_log.read(kind="spawned"):
    print(event["agent_id"], event["payload"]["child_id"])
for event in runtime.boundary_log.read(kind="settled"):
    print(event["agent_id"], event["payload"]["status"])
```

## 6. Stop

```python
runtime.stop()
```

## Where to go next

- Every name an action block can call: [agent-api.md](agent-api.md) —
  generated from the registry, always current.
- The two CLI entry points (chat, operator terminal):
  `docs/breakdown/05-operation/the-two-entry-points.md`.
- The end-to-end value demonstration: `examples/value_demo.py`.
- The integration test behind this tutorial: `tests/test_integration.py`.
