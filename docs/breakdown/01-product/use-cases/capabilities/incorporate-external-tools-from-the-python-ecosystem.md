---
id: INFO-044
type: info
title: Incorporate external tools from the Python ecosystem
summary: Agents and users load RAG, web search, and memory packages themselves, so the harness stays a substrate while the ecosystem moves
date: 2026-10-06
status: draft
---

# Incorporate external tools from the Python ecosystem

- **Ecosystem moves faster**
  - Ecosystem moves faster than any release cycle.
  - RAG stacks, web search and manipulation APIs, memory architectures appear and shift between harness releases.
- **Harness stays substrate**
  - Harness adopts none of them.
  - Current technology never becomes built-in runtime must chase.
- **Agent-side, user-side incorporation**
  - Capability arrives as Python package agent or user loads mid-run, through extension contract (`INFO-007`).
- **Quick adaptation committed**
  - New external development usable in same session it appears in.
  - No harness change, no waiting.
- **In-code capability surface**
  - Mechanism incorporation flows through: loadable tools and free verbs, not new harness plumbing.
- **Scope today**
  - Retrieval (RAG), web search and manipulation, memory architectures.
  - Package categories use cases name.

## Owns
- External-tool-incorporation use cases: RAG, web search/manipulation, memory architectures incorporated from Python ecosystem, agent-side and user-side.

## Excludes
- Extension contract incorporation loads packages through — `INFO-007`.
