---
id: INFO-007
type: info
title: Extend capabilities with agent tools
summary: Agents add capabilities outside the harness release cycle so the harness stays a substrate
date: 2026-10-05
status: current
---

# Extend capabilities with agent tools

- Agents extend the capability surface themselves, outside the harness release cycle (`INFO-001`).
- The harness is a substrate, not a tool set: capabilities arrive as artifacts and code, not built-ins.
- Harness plumbing stays runtime-owned and invisible — instrumentation is never agent-authored.
- Loaded tools persist in the agent's own REPL, so a capability the agent adds stays available (`INFO-050`).

## Owns
- The agent-developed-tools extension contract.

## Excludes
- The core action loop the tools extend — `INFO-002`.
- The hosting boundary the extensions live inside — `INFO-008`.
