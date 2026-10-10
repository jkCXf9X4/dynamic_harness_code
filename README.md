# dhc — Dynamic Harness Code

A **recursive agent runtime** where every agent turn is **one Python block**
executed against a **per-agent persistent REPL**. Agents decompose work by
writing delegation code, supervise children with fork/join semantics, and
report through content-addressed artifacts — all under ISO/IEC 15288
V-model discipline (analyze → decompose → delegate → verify → synthesize →
terminate).

**Why dhc exists** — mission, principles, and boundaries — lives in
[`breakdown/00-intent/`](breakdown/00-intent/). The full current-state map
starts at [`breakdown/README.md`](breakdown/README.md).

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

With an API key the real LLM path activates: `export OPENAI_API_KEY=sk-...`
then `dhc` (real LLM driver, gpt-4o by default). The full quick start and the
end-to-end value demonstration live in
[`breakdown/05-operation/`](breakdown/05-operation/).

## The map

- **Why it exists** — [`breakdown/00-intent/`](breakdown/00-intent/)
- **What it promises** — [`breakdown/01-product/`](breakdown/01-product/),
  driven by the use-case leaves under
  [`breakdown/01-product/use-cases/`](breakdown/01-product/use-cases/)
- **How it is organized** —
  [`breakdown/02-architecture/`](breakdown/02-architecture/) (runtime
  composition, INFO-058)
- **Where the code lives** —
  [`breakdown/03-implementation/`](breakdown/03-implementation/) (module
  map, INFO-055)
- **How claims are checked** —
  [`breakdown/04-verification/`](breakdown/04-verification/) (INFO-056); the
  suite itself: [`tests/`](tests/)
- **How it is run** — [`breakdown/05-operation/`](breakdown/05-operation/)
  (INFO-057)
- **What might change** — [`breakdown/06-evolution/`](breakdown/06-evolution/)
