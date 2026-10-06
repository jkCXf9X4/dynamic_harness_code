---
id: INFO-001
type: info
title: VISION
summary: Mission, principles, action loop, and boundaries for code-as-action-space
date: 2026-10-05
status: current
pb_exempt: true
---

# VISION

**Dynamic Harness Code (dhc) is a recursive agent runtime that maximizes LLM output
quality while minimizing cost — by making executable Python the action space: every
agent turn writes code, the runtime executes it in a disposable sandbox, and
ISO/IEC 15288 V-model discipline is enforced on every action.**

One expressive code block replaces N tool-call turns: loops, fan-out, transforms, and
error handling happen inside a single action. This compounds fresh-context economics —
decomposed 3-turn workers beat a 20-turn monolith on both cost and quality
(~3K delegation overhead < >15K context rot), and the code block is the mechanism that
keeps agent turns few.

## The action loop

1. The agent emits Python for its turn.
2. The runtime persists the code as an immutable artifact, then executes it against the agent's persistent REPL in its own subprocess.
3. The V-model is the shape of every action: the code analyzes its allocated
   requirement, implements, verifies against the parent's acceptance criteria, and
   reports — a small V per turn.

## Principles

1. **Container-hosted.** The full dhc runtime runs inside Docker/Podman — the outer
   security and deployment boundary.
2. **Agent = unit of execution.** Every agent is wrapped in its own thread/process; a
   crashed child is contained in its thread and surfaces as a failed result.
3. **Clean Python, injected traceability.** Agent code is python; all
   harness plumbing is runtime-owned and invisible — instrumentation is never agent-authored.
4. **Agent-developed tools.** Capabilities are extensible by agents themselves, outside
   the harness release cycle — the harness is a substrate, not a tool set.
5. **Recursive task decomposition.** Parents decompose by writing delegation code. 
6. **Context encapsulation.** 
7. **Artifact-driven communication.** Findings, results, and every action's code persist
   as immutable, content-addressed artifacts; parents receive summaries plus artifact IDs.
8. **Progressive disclosure.** Artifacts expose headline → summary → report tiers; consumers
   pull detail on demand.
9. **Per-agent persistent REPL.** Every agent works in a persistent computational workspace of its
   own — REPL state persists across actions, agent-developed tools live in it, and artifacts remain
   the durable medium for findings that cross agents or must outlive the agent.

## Inspirations

- **dynamic_harness** — V-model discipline, encapsulation, context economics carry over; tool calls do not.
- **CodeAct** — executable code actions elicit better LLM agents.
- **ISO/IEC 15288** — V-model, system breakdown structure.
- **Actor model** (Erlang, Akka) — private state, message passing, supervision.
- **Distributed builds** (Bazel, Nix) — immutable artifacts, reproducibility.
- **Operating systems** — process isolation, disposable processes.
