# dhc — Dynamic Harness Code

A recursive agent runtime where every agent turn is **one Python block**
executed against a **per-agent persistent REPL**. Agents decompose work by
writing delegation code, supervise children with fork/join semantics, and
report through content-addressed artifacts — all under ISO/IEC 15288 V-model
discipline (analyze → decompose → delegate → verify → synthesize →
terminate). The package is fully wired: `build_runtime()` in `wiring.py`
assembles the real modules into a working runtime, and the `dhc` console
script is a thin chat-only TUI on top of it.

## Layout

```
src/dhc/
├── __init__.py      # public re-export surface (subpackages exposed as attributes)
├── cli.py           # `dhc` console entry point — thin chat-only TUI (INFO-028)
├── wiring.py        # composition root: build_runtime() wires all real modules
├── errors.py        # cross-cutting error hierarchy (DhcError + subclasses)
├── agent/           # agent-controlled execution core (store/channel-unaware,
│                    #   0014/0015); owns the directed-message primitive (send)
├── llm/             # LLM provider plumbing
├── ui/              # operator surface
├── data/            # schemas, config
├── tooling/         # operator tooling: artifact store, boundary log,
│                    #   communication channels + their tools (0014/0015)
└── benchmark/       # failable-verifier benchmark suite
```

### agent/ — the agent-controlled execution core

| module | what it is |
|---|---|
| `runtime.py` | The runtime orchestrator: agent registry, thread-per-agent placement, worker loop (driver → turn → settle), at-most-once completion dispatch, cancellation, and the directed-message primitive `send` (0015) |
| `repl.py` | Per-agent persistent REPL engine (INFO-050): one private workspace per agent, serialized turns, crash containment |
| `agent.py` | The in-code agent surface: `Agent` (what action blocks see as `agent`) and `AgentHandle` (the parent's await/poll/cancel handle) |
| `tools.py` | The framework tools layer: `list_tools` + `events` as REPL namespace callables (the channel and store tools live in `tooling/`) |
| `state.py` | Run-overview persistence for manual review: `agent_tree.json`, `stats.json`, `agents.txt`, `events.jsonl` |
| `checkpoint.py` | Per-agent checkpoint persistence (peripheral wrapper, best-effort save/restore) |
| `event_stream.py` | Event stream, runtime-owned event bus, and completion dispatcher (persist-before-execute, at-most-once) |

### llm/ — provider plumbing

| module | what it is |
|---|---|
| `llm.py` | Provider abstraction (`LLMProvider` / `OpenAIProvider`), the mock path (`MockLLM`), timeout containment, context-rot detection |
| `driver.py` | The pluggable brain: `LLMDriver` (real) and `MockDriver` (deterministic) turn a requirement into coded action blocks |
| `prompts.py` | Single place prompts are shaped: static system prompt (`agent_system_prompt.txt`) + steerage block, composed once for prompt caching |
| `fabrication.py` | The fabrication kit (IMP-001 D4): default `__runner` + `decide(context)` and the workspace citizens |

### ui/ — the operator surface

| module | what it is |
|---|---|
| `terminal.py` | Prompt-only interactive terminal: one root agent across turns, `/`-commands, batch mode |
| `operator.py` | The single human↔mesh door (INFO-017): chat loop, mid-turn steering (via the core `send` primitive, 0015), operator questions |

### data/ — schemas, config

| module | what it is |
|---|---|
| `models.py` | Core pydantic v2 value objects: `Artifact`, `Result`, `Event`, `Completion`, `Room`, `Turn`, … |
| `config.py` | Runtime configuration: env/`.env` `Settings` singleton + layered `harness.json` discovery (XDG → cwd → explicit) |
| `trace.py` | Per-agent `trace.jsonl` persistence (peripheral wrapper) |

### tooling/ — operator tooling (decisions 0014/0015)

The framework core is store-unaware and channel-unaware: it knows artifacts
only as opaque ids and the `artifact_published` event, and communication
only as the directed-message primitive (`Runtime.send` / `Agent.send`).
Everything composed over those contracts lives here, instantiated only by
the composition root — so the agent keeps full control of its communication
patterns and persistence stack.

| module | what it is |
|---|---|
| `artifact_store.py` | Immutable content-addressed artifact store + append-only boundary event log |
| `artifact_tools.py` | The store's REPL tools (`publish`, `read_artifact`, `archive`, `list_artifacts`) + `register_artifact_tools` |
| `channels.py` | The communication policies over the core `send` primitive: `Messenger` (inbox view), `RoomManager`, `EscalationChannel`, `OperatorQuestionChannel` |
| `channel_tools.py` | The channels' REPL tools (`room`, `messenger`, `escalate`, `ask_operator`, `post`, `channel_read`) + `register_channel_tools` |
| `adapters.py` | `StoreAdapter` (`put` → `publish(h, s, r)` + read tiers) and `BoundarySink` (events → boundary log) |

### benchmark/ — evaluation

| module | what it is |
|---|---|
| `tasks.py` | Benchmark tasks with failable ground-truth verifiers (largest-files, fibonacci, synthesis) |
| `run.py` | The runner: fresh Runtime per (prompt, task), staged workspace, JSON + Markdown results |
| `metrics.py` | Per-run metrics schema (`RunMetrics`) |
| `scoring.py` | Deterministic weighted rubric scoring (correctness gate + efficiency) |

## Install

```bash
pip install -e .
```

Python 3.10. The install registers the `dhc` console script.

## Run

```bash
dhc                          # chat TUI (real driver if OPENAI_API_KEY is set, else mock)
dhc --mock                   # deterministic mock driver, no API key needed
dhc --inspect AGENT_ID       # print a read-only workspace view and exit
dhc --context F --transcript F   # custom context/transcript files (default .dhc/*.md)
```

The prompt-only interactive terminal (with `/`-commands) is
`dhc.ui.terminal:main`; the benchmark runs via `python -m dhc.benchmark.run`.

## See also

- `tests/` — the pytest suite, mirroring this layout (see `tests/README.md`)
- `examples/value_demo.py` — end-to-end demo with hard evidence (see `examples/README.md`)
- `../README.md` — project overview and design decisions
