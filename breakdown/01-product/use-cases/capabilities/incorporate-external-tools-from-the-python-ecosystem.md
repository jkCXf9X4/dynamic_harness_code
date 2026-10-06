---
id: INFO-044
type: info
title: Incorporate external tools from the Python ecosystem
summary: Agents and users load RAG, web search, and memory packages themselves, so the harness stays a substrate while the ecosystem moves
date: 2026-10-06
status: draft
---

# Incorporate external tools from the Python ecosystem

- The ecosystem moves faster than any release cycle: RAG stacks, web search and manipulation APIs, and memory architectures appear and shift between harness releases.
- The harness stays a substrate — it adopts none of them, so a current technology never becomes a built-in the runtime must chase.
- Incorporation is agent-side and user-side: a capability arrives as a Python package an agent or user loads mid-run, through the extension contract (`INFO-007`).
- Quick adaptation is the committed behavior: new external development is usable in the same session it appears in, with no harness change and no waiting.
- The in-code capability surface (`INFO-029`) is the mechanism incorporation flows through — loadable tools and free verbs, not new harness plumbing.
- Scope today: retrieval (RAG), web search and manipulation, and memory architectures — the package categories the use cases name.

## Owns
- The external-tool-incorporation use cases: RAG, web search/manipulation, and memory architectures incorporated from the Python ecosystem, agent-side and user-side.

## Excludes
- The extension contract incorporation loads packages through — `INFO-007`.
- The in-code capability surface candidate carrying the mechanism — `INFO-029`.
