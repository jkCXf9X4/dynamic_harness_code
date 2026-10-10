---
id: INFO-041
type: info
title: Keep the code interface public and decoupled
summary: The in-code capability surface counts as public interface, so it stays decoupled from the harness and can be developed as a separate entity
date: 2026-10-06
status: draft
---

# Keep the code interface public and decoupled

- The stance: the code interface — the in-code capability surface agent code programs against — is part of the public interface, not an internal harness detail.
- Holding the code interface public keeps it decoupled from the harness, so agents can continue developing it as a separate entity.
- Its first public pieces are the tool extension (`INFO-007`) and the minimal execution-core contract (`INFO-037`).

## Owns
- The public-interface stance on the code interface: public, decoupled, separately developed.

## Excludes
- The harness machinery the code interface stays decoupled from — organized in `02-architecture/`.
