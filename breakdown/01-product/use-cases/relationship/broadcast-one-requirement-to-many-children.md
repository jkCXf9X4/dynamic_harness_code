---
id: INFO-013
type: info
title: Broadcast one requirement to many children
summary: A parent spawns many children with the same requirement differing only in one parameter and picks among the results
date: 2026-10-05
status: current
---

# Broadcast one requirement to many children

- **Right approach unknowable up front** (`INFO-004`).
  - Complex problem: parent spawns many children with the same requirement.
  - Copies differ only in one parameter.
- **Parallel, contained individually** (`INFO-005`).
  - All children run in parallel.
  - Each child is contained individually.
- **Point-to-point answers** (`INFO-006`).
  - Every child answers with a summary plus artifact IDs.
  - Parent picks among the returned results: ensemble or parallel probe.
- **Exploratory probe.**
  - Parent commits to a direction only after seeing the results.
  - Probe-sense-respond.

## Owns
- One-to-many broadcast with parameterized copies of one requirement.

## Excludes
- Fan-out with distinct subtasks per child — `INFO-009`.
- In-task re-decomposition — `INFO-010`.
- The artifact contract the results ride on — `INFO-006`.
