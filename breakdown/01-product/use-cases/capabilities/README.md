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
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-002** [Run a coded action](run-a-coded-action.md) — A worker turn becomes one Python block the runtime persists and executes against the agent's persistent REPL
- **INFO-007** [Extend capabilities with agent tools](extend-capabilities-with-agent-tools.md) — Agents add capabilities outside the harness release cycle so the harness stays a substrate
- **INFO-020** [Survive an LLM call timing out or terminating](survive-an-llm-call-timing-out-or-terminating.md) — A timed-out or terminated LLM call fails the turn safely and surfaces as a failed result instead of hanging or crashing the agent
- **INFO-021** [Detect context rot in an agent's output](detect-context-rot-in-an-agent-s-output.md) — The runtime detects degradation signatures in an agent's output; the agent's rot policy (observe-only default, or escalate) decides whether a trip settles the agent and surfaces to the parent
- **INFO-041** [Keep the code interface public and decoupled](keep-the-code-interface-public-and-decoupled.md) — The in-code capability surface counts as public interface, so it stays decoupled from the harness and can be developed as a separate entity
- **INFO-044** [Incorporate external tools from the Python ecosystem](incorporate-external-tools-from-the-python-ecosystem.md) — Agents and users load RAG, web search, and memory packages themselves, so the harness stays a substrate while the ecosystem moves
- **INFO-050** [The agent REPL](the-agent-repl.md) — Every agent works in a persistent REPL of its own — a private computational workspace whose state survives across actions, that all of the agent's code executes in and never concurrently, that hosts the turn engine as workspace code (the `__runner` generator, default shipped as a fabrication), and that nothing crosses except explicit context in and explicit results out
- **INFO-051** [The event stream](the-event-stream.md) — The runtime-owned stream of settled events arriving to an agent — per AD-006, consumption is the agent's (in-loop, read as ordinary data) while the discipline (FIFO, at-most-once, persist-before-execute) stays runtime-owned, and registration is by held handle
<!-- pb:index:end -->
