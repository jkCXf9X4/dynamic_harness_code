---
title: Own execution
summary: One agent's own action loop, verification, resilience, and persistent state
---

# Own execution

How the harness runs a single agent in isolation: the turn-as-code loop, its
persistent REPL and output history, and its resilience to failure.

## Owns
- Single-agent behaviors, regardless of what the agent works on.

## Excludes
- Coordination with other agents — `delegation/`, `peers/`.

## Contents

<!-- pb:index:start -->
- **INFO-002** [Run a coded action](run-a-coded-action.md) — A worker turn becomes one Python block the runtime persists and executes against the agent's persistent REPL
- **INFO-003** [Self-verify a turn](self-verify-a-turn.md) — Each action block analyzes its requirement, implements, verifies against the parents acceptance criteria, and reports
- **INFO-020** [Survive an LLM call timing out or terminating](survive-an-llm-call-timing-out-or-terminating.md) — A timed-out or terminated LLM call fails the turn safely and surfaces as a failed result instead of hanging or crashing the agent
- **INFO-021** [Detect context rot in an agent's output](detect-context-rot-in-an-agent-s-output.md) — The runtime detects degradation signatures such as repeating loops and gibberish in an agent's output stream and surfaces them to the parent
- **INFO-026** [Compress a running agent's context](compress-a-running-agent-s-context.md) — Collapse accumulated context into a summary that leans on persisted artifacts, the committed remedy for detected context rot short of re-decomposition
- **INFO-035** [Keep an output history distinct from REPL state](keep-an-output-history-distinct-from-repl-state.md) — Explicitly returned outputs are retained as a queryable history, separate from the agent's working variables
- **INFO-037** [Commit to a minimal execution-core contract](commit-to-a-minimal-execution-core-contract.md) — The execution behaviors lack a committed minimal contract; candidate: persistent REPL, non-blocking delegate, await/poll/callback/cancel, with observability at boundaries only
- **INFO-038** [Run each agent in its own thread or process](run-each-agent-in-its-own-thread-or-process.md) — Every agent executes in its own thread-or-process unit, isolated from the runtime process and from every other agent
- [commit-to-a-minimal-execution-core-contract.analysis](commit-to-a-minimal-execution-core-contract.analysis.md)
<!-- pb:index:end -->
