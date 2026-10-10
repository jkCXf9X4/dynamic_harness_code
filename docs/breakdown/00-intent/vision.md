---
id: INFO-001
type: info
title: VISION
summary: Mission, principles, action loop, boundaries. Code as action space. Framework core vs operator tooling.
date: 2026-10-10
status: current
pb_exempt: true
---

# VISION

**Dynamic Harness Code (dhc) is a recursive agent runtime. It maximizes LLM output quality and minimizes cost. Executable Python is the action space: every agent turn writes code. Runtime executes it in a disposable sandbox. ISO/IEC 15288 V-model discipline is enforced on every action.**

- **Fewer turns.** One expressive code block replaces N tool-call turns.
- **One action.** Loops, fan-out, transforms, error handling happen inside a single action.
- **Fresh-context economics.** Decomposed 3-turn workers beat a 20-turn monolith on cost and quality (~3K delegation overhead vs >15K context rot).
- **Mechanism.** The code block keeps agent turns few.

Direction riding this substrate: agent owns its execution; platform is a minimal guardian (`INFO-052`).

## The action loop

- **Emit.** Agent emits Python for its turn.
- **Persist.** Runtime persists code as immutable artifact.
- **Agent-owned loop.**
  - Loop itself is agent-authored workspace code, living in the agent's REPL (`INFO-050`, `INFO-037`).
  - Runtime pumps it one step at a time.
- **V-model per turn.** Code analyzes its allocated requirement, implements, verifies against parent's acceptance criteria, reports. Small V per turn.

## Principles

- **Container-hosted.** Full dhc runtime runs inside Docker/Podman, the outer security and deployment boundary.
- **Agent = unit of execution.**
  - Every agent wraps in its own thread/process.
  - Failed child is contained, rolled back, settles failed (`INFO-005`).
  - Workspace is the blast radius.
- **Clean Python, runtime-owned plumbing.**
  - Agent code is Python. Harness plumbing is runtime-owned.
  - Control split is who enforces, not visibility: plumbing is visible to the agent (`INFO-053`).
  - Agent reads and manages its full state as ordinary data. No pre-filtered view of itself. No hidden state.
  - Rot detection is runtime-owned instrumentation: invisible by default, authorable by explicit opt-in (`INFO-021`).
  - Rot policy `context.rot_policy` (threshold and reaction) is ordinary workspace data the agent may author and edit.
  - Rot policy is observe-only by default.
  - Agent may loosen or tighten it, within the ceiling caps (`INFO-053`).
- **Agent-developed tools.**
  - Capabilities are extensible by agents themselves, outside harness release cycle.
  - Harness is substrate, not tool set.
- **Recursive task decomposition.** Parents decompose by writing delegation code.
- **Context encapsulation.**
  - Agent's context is its scarcest resource.
  - Work crosses agents as content-addressed ids and summaries, never as full bodies.
  - Mesh shares findings without polluting each other's context.
  - Detail pulls tier by tier, only when consumer needs it (`INFO-006`, `INFO-012`).
- **Immutable, verifiable artifacts.**
  - Whatever crosses the mesh — findings, results, code of every action — is an immutable, content-addressed artifact.
  - Handed-off claim cannot silently change. Its id proves what it contains.
  - Delivery — protocol, tiers, storage — is architecture, not vision (`INFO-006`, `AD-008`).
- **Progressive disclosure.**
  - Artifacts expose headline, summary, report tiers.
  - Consumers pull detail on demand.
- **Per-agent persistent REPL.**
  - Every agent works in a persistent computational workspace of its own.
  - REPL state persists across actions. Agent-developed tools live in it.
  - Artifacts remain the durable medium for findings crossing agents or outliving the agent.
- **Core owns the contract.**
  - Framework core is a small, stable set of guarantees.
  - Guarantee set is the runtime-control list plus the directed-message primitive (`INFO-053`, `INFO-054`).
  - Any agent can `send` to any other by identity.
  - Message is guaranteed to reach the recipient's awareness (`AD-009`).
- **Operator owns the medium.**
  - Operator needs: persisting, observing, rendering state.
  - Every communication pattern above direct messaging — rooms, escalation routing, operator questions — is tooling composed around the core.
  - Tooling is one-way dependent on the core, never inside it.
  - Agent's communication beyond the primitive is its own composition choice.
  - Where the line falls for a new concern is decided in the architecture (`INFO-054`, `AD-008`, `AD-009`).

## Inspirations

- **dynamic_harness**
  - V-model discipline, encapsulation, context economics carry over. Tool calls do not.
- **CodeAct**
  - Executable code actions elicit better LLM agents.
- **ISO/IEC 15288**
  - V-model, system breakdown structure.
- **Actor model** (Erlang, Akka)
  - Private state, message passing, supervision.
- **Distributed builds** (Bazel, Nix)
  - Immutable artifacts. Reproducibility.
- **Operating systems**
  - Process isolation. Disposable processes.
