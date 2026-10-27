# dhc — Dynamic Harness Code

A **recursive agent runtime** where every agent turn is **one Python block**
executed against a **per-agent persistent REPL**. Each turn follows a small V:
analyze its requirement, implement, verify against the parent's acceptance
criteria. Agents decompose work by writing delegation code, supervise children
with fork/join semantics, and report through content-addressed artifacts.

**Why dhc exists** — mission, principles, boundaries, and the agent-owned
direction — lives in [`docs/breakdown/00-intent/`](docs/breakdown/00-intent/). The full current-state map
starts at [`docs/breakdown/README.md`](docs/breakdown/README.md).

## What dhc is

- **One turn = one Python block** (INFO-002). Loops, fan-out, selective
  failure handling and verification all happen *inside* the block — one
  expressive block replaces N tool-call turns.
- **Per-agent persistent REPL** (INFO-050). Variables, functions and imports
  survive between turns; each agent's workspace is isolated from every other
  agent's.
- **Agent-owned split** (INFO-074). The framework supplies instruments;
  the agent owns orchestration and policy.
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

**1. Install**

```bash
pip install -e .
```

**2. Run the demo** — a complete end-to-end session in mock mode
(deterministic, no API key, no network; finishes in well under a minute):

```bash
python3 examples/value_demo.py
```

Exit code 0 on success. The demo runs a root agent that receives a
**requirement**, **spawns** three children, **awaits** them, aggregates
their **artifacts**, and **completes** — while one child **fails** and its
siblings still finish.

**3. The concepts** — that's the whole mental model:

- **requirement** — the task an agent is spawned with; the unit of work.
- **spawn / await** — a parent spawns children (non-blocking) and awaits
  them (ensure-terminal) before settling.
- **complete / fail** — every agent settles in exactly one terminal state,
  `completed` or `failed`; a failed child never takes down its siblings.
- **artifacts (publish / read)** — findings persist as immutable,
  content-addressed artifacts; parents read summaries + ids and pull
  detail on demand.

**Everything else is a link away:**

- The hands-on tutorial (every code block executed by CI):
  [`docs/quickstart.md`](docs/quickstart.md)
- Every name an agent's action block can call (generated, always
  current): [`docs/agent-api.md`](docs/agent-api.md)
- The two CLI entry points — `dhc --mock` chat (echo-only: it never calls
  an LLM; the banner says so) and the real-LLM operator terminal:
  [`docs/breakdown/05-operation/the-two-entry-points.md`](docs/breakdown/05-operation/the-two-entry-points.md)
- Full quick start and the value demonstration:
  [`docs/breakdown/05-operation/quick-start.md`](docs/breakdown/05-operation/quick-start.md)
- Artifacts in depth:
  [`docs/breakdown/01-product/use-cases/artifacts/publish-and-consume-artifacts.md`](docs/breakdown/01-product/use-cases/artifacts/publish-and-consume-artifacts.md)
- All use cases (fan-out, crash containment, recursive decomposition, ...):
  [`docs/breakdown/01-product/use-cases/`](docs/breakdown/01-product/use-cases/)

## The map

- **Why it exists** — [`docs/breakdown/00-intent/`](docs/breakdown/00-intent/)
- **What it promises** — [`docs/breakdown/01-product/`](docs/breakdown/01-product/),
  driven by the use-case leaves under
  [`docs/breakdown/01-product/use-cases/`](docs/breakdown/01-product/use-cases/)
- **How it is organized** —
  [`docs/breakdown/02-architecture/`](docs/breakdown/02-architecture/) (runtime
  composition, INFO-058)
- **Where the code lives** —
  [`docs/breakdown/03-implementation/`](docs/breakdown/03-implementation/) (module
  map, INFO-055)
- **How claims are checked** —
  [`docs/breakdown/04-verification/`](docs/breakdown/04-verification/) (INFO-056); the
  suite itself: [`tests/`](tests/)
- **How it is run** — [`docs/breakdown/05-operation/`](docs/breakdown/05-operation/)
  (INFO-057)
- **What might change** — [`docs/breakdown/06-evolution/`](docs/breakdown/06-evolution/)

## Tests

- Full suite (default, every test): `.venv/bin/python -m pytest -q` (or `make test`)
- Fast lane, opt-in only: `.venv/bin/python -m pytest -q -m "not slow"` (or `make test-fast`); the `slow` marker covers the heavy end-to-end suites (runtime lifecycle, event durability, mesh survival)
