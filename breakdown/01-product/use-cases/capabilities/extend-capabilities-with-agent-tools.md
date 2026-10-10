---
id: INFO-007
type: info
title: Extend capabilities with agent tools
summary: Agents add capabilities outside the harness release cycle so the harness stays a substrate
date: 2026-10-05
status: current
---

# Extend capabilities with agent tools

- **Agent-side extension**
  - Agents extend capability surface themselves, outside harness release cycle (`INFO-001`).
- **Substrate, not tool set**
  - Capabilities arrive as artifacts and code, not built-ins.
- **Runtime-owned plumbing**
  - Harness plumbing stays runtime-owned and invisible. Instrumentation never agent-authored.
- **Loaded tools persist**
  - Loaded tools persist in agent's own REPL (`INFO-050`).
  - Capability agent adds stays available.

## Owns
- Agent-developed-tools extension contract.

## Excludes
- Core action loop tools extend — `INFO-002`.
- Hosting boundary extensions live inside — `INFO-008`.
