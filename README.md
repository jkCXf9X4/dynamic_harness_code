# dhc — Dynamic Harness Code

A **recursive agent runtime** where every agent turn is **one Python block**
executed against a **per-agent persistent REPL**. Agents decompose work by
writing delegation code, supervise children with fork/join semantics, and
report through content-addressed artifacts — all under ISO/IEC 15288
V-model discipline (analyze → decompose → delegate → verify → synthesize →
terminate).

## What dhc is

- **One turn = one Python block** (INFO-002). Loops, fan-out, selective
  failure handling and verification all happen *inside* the block — one
  expressive block replaces N tool-call turns.
- **Per-agent persistent REPL** (INFO-050). Variables, functions and imports
  survive between turns; each agent's workspace is isolated from every other
  agent's.
- **Delegation by writing code** (INFO-004). A parent spawns children with
  encapsulated context (requirement + acceptance + explicit inputs), awaits
  them (ensure-terminal), and aggregates their results.
- **Crash containment** (INFO-005). A crashed child never takes down a
  sibling or the parent; the failure surfaces as one distinguishable
  `failed` terminal state.
- **At-most-once settlement** (INFO-046). One settled child = one completion;
  double settlement is rejected.
- **Progressive-disclosure artifacts** (INFO-006). Findings persist as
  immutable, content-addressed artifacts with three tiers — `headline` →
  `summary` → `report` — so parents receive summaries + ids and pull detail
  on demand.
- **Boundary event log** (INFO-049). Five event kinds (`spawned`, `settled`,
  `cancelled`, `published`, `messaged`) with causal ids reconstruct
  concurrent work as a DAG.

## Quick start

```bash
pip install -e .
dhc --mock            # minimal chat TUI, deterministic mock driver, no API key
```

With an API key the real LLM path activates:

```bash
export OPENAI_API_KEY=sk-...
dhc                   # real LLM driver (gpt-4o by default)
```

## Architecture

```
operator (root door) ──> Runtime ──> per-agent worker thread
                        │             └─> ReplEngine (persistent REPL)
                        │             └─> driver (LLMDriver | MockDriver)
                        ├─> EventBus ──> BoundaryEventLog (persist sink)
                        ├─> CompletionDispatcher (at-most-once, FIFO)
                        ├─> ArtifactStore (content-addressed, 3 tiers)
                        └─> channels: Messenger, RoomManager,
                                      EscalationChannel, OperatorQuestionChannel
```

`dhc.wiring.build_runtime(settings=None, mock=False)` wires the real modules
together and returns a ready `Runtime` with the channels and the operator
tooling exposed (`runtime.messenger`, `runtime.rooms`, `runtime.escalations`,
`runtime.questions`, `runtime.operator`, `runtime.boundary_log`,
`runtime.artifact_store`).

## Module map

| Module | Owns |
| --- | --- |
| `models.py` | `Artifact`, `Result`, `Event`, `Completion`, `ToolOutput`, `Room`, lifecycle states |
| `errors.py` | the `DhcError` hierarchy |
| `config.py` | `Settings` (env + `.env`), `get_settings()` |
| `tooling/artifact_store.py` | content-addressed `ArtifactStore`, `BoundaryEventLog` (INFO-049) — operator tooling (0014) |
| `tooling/artifact_tools.py` | the store's REPL tools: `publish`, `read_artifact`, `archive`, `list_artifacts` |
| `repl.py` | per-agent persistent `ReplEngine` (INFO-050) |
| `event_stream.py` | `EventStream`, `EventBus`, `CompletionDispatcher` (INFO-046/047/048) |
| `agent.py` | the in-code surface: `Agent`, `AgentHandle`, `bash`, `room` |
| `runtime.py` | `Runtime`: spawn/await/poll/cancel/status/result, parent liveness, worker loop |
| `llm.py` | `LLMClient`, `MockLLM`, `ContextRotDetector` (INFO-020/021) |
| `driver.py` | `LLMDriver`, `MockDriver`, `driver_from_settings` — the pluggable brain |
| `communication.py` | `Messenger`, `RoomManager`, `EscalationChannel`, `OperatorQuestionChannel` |
| `operator.py` | root door, chat loop, mid-turn steering, operator questions |
| `cli.py` | minimal chat-only TUI (INFO-028) |
| `wiring.py` | `build_runtime` — binds the real modules into one runtime |

## Running the tests

```bash
python3 -m pytest -q        # full suite (unit + integration)
python3 -m pytest tests/test_integration.py -q   # end-to-end wiring only
```

The integration tests use the deterministic `MockDriver` — no network, no
API key.

## Value demonstration

```bash
python3 examples/value_demo.py
```

Runs a complete end-to-end session on the fully-wired runtime (root →
publish → fan-out to 3 children → one child fails → parent aggregates →
settle) and writes a structured report to
`.dynamic-harness/261006_230325_4a23/artifacts/value_demo_report.md`
answering *what value dhc provides during agent work*: one coded action
replaces N tool-call turns, progressive disclosure saves context, crash
containment keeps siblings alive, at-most-once settlement prevents duplicate
work, and parent liveness holds until children settle. If `OPENAI_API_KEY`
is set, one real-LLM turn is also run to prove the real path.

## Use cases

The design is driven by the use-case leaves under
[`breakdown/01-product/use-cases/`](breakdown/01-product/use-cases/) and the
architecture leaves under
[`breakdown/02-architecture/`](breakdown/02-architecture/); the binding
implementation contract is
[`breakdown/02-architecture/pre-studies/mockups/_support.py`](breakdown/02-architecture/pre-studies/mockups/_support.py).