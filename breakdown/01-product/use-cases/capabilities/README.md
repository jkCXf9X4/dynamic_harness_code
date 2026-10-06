---
title: Capabilities and the primitive surface
summary: Extending what agents can do, and the minimal execution-core contract behind it
---

# Capabilities and the primitive surface

Use cases about the capability surface itself: how agents extend it and what
minimal primitive contract it commits to.

## Owns
- The capability surface as a product commitment.

## Excludes
- The individual use cases that surface fulfills — the other groups.

## Contents

<!-- pb:index:start -->
- **INFO-002** [Run a coded action](run-a-coded-action.md) — A worker turn becomes one Python block the runtime persists and executes against the agent's persistent REPL
- **INFO-007** [Extend capabilities with agent tools](extend-capabilities-with-agent-tools.md) — Agents add capabilities outside the harness release cycle so the harness stays a substrate
- **INFO-020** [Survive an LLM call timing out or terminating](survive-an-llm-call-timing-out-or-terminating.md) — A timed-out or terminated LLM call fails the turn safely and surfaces as a failed result instead of hanging or crashing the agent
- **INFO-021** [Detect context rot in an agent's output](detect-context-rot-in-an-agent-s-output.md) — The runtime detects degradation signatures such as repeating loops and gibberish in an agent's output stream and surfaces them to the parent
- **INFO-030** [Give each agent a persistent REPL](give-each-agent-a-persistent-repl.md) — Every agent works in a persistent REPL of its own — state persists across actions, context passes explicitly at delegation boundaries, and nothing is shared implicitly
- **INFO-038** [Run each agent in its own thread or process](run-each-agent-in-its-own-thread-or-process.md) — Every agent executes in its own thread-or-process unit, isolated from the runtime process and from every other agent
- **INFO-041** [Keep the code interface public and decoupled](keep-the-code-interface-public-and-decoupled.md) — The in-code capability surface counts as public interface, so it stays decoupled from the harness and can be developed as a separate entity
- **INFO-044** [Incorporate external tools from the Python ecosystem](incorporate-external-tools-from-the-python-ecosystem.md) — Agents and users load RAG, web search, and memory packages themselves, so the harness stays a substrate while the ecosystem moves
<!-- pb:index:end -->
