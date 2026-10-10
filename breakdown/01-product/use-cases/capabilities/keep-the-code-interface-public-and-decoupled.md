---
id: INFO-041
type: info
title: Keep the code interface public and decoupled
summary: The in-code capability surface counts as public interface, so it stays decoupled from the harness and can be developed as a separate entity
date: 2026-10-06
status: draft
---

# Keep the code interface public and decoupled

- **Public-interface stance**
  - Code interface (in-code capability surface agent code programs against) counts as public interface.
  - Not internal harness detail.
- **Decoupled**
  - Holding code interface public keeps it decoupled from harness.
  - Agents can continue developing it as separate entity.
- **First public pieces**
  - Tool extension (`INFO-007`).
  - Minimal execution-core contract (`INFO-037`).

## Owns
- Public-interface stance on code interface: public, decoupled, separately developed.

## Excludes
- Harness machinery code interface stays decoupled from, organized in `02-architecture/`.
