---
id: INFO-041
type: info
title: Keep the code interface public and decoupled
summary: The in-code capability surface counts as public interface, so it stays decoupled from the harness and can be developed as a separate entity
date: 2026-10-06
status: draft
---

# Keep the code interface public and decoupled

- The stance: the code interface — the in-code capability surface agent code programs against (`INFO-029`) — is part of the public interface, not an internal harness detail.
- Why it belongs here: holding it as public interface forces it to stay sufficiently decoupled from the harness, so agents can continue developing the code interface as a separate entity.
- What it commits to today: the minimal execution-core contract draft (`INFO-037`) and tool extension (`INFO-007`) are its first public pieces.

## Owns
- The public-interface stance on the code interface: public, decoupled, separately developed.

## Excludes
- The harness machinery the code interface stays decoupled from — organized in `02-architecture/`.
- The full capability-surface candidate — `INFO-029`.
