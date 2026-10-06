---
title: The V-model
summary: Turn-as-code decomposition and self-verification — decompose recursively, self-verify each turn
date: 2026-10-06
status: current
---

# The V-model

How work is shaped before and within the mesh: recursive decomposition into child workers, and self-verification of each turn against the parent's acceptance criteria. Facts here answer "how does an agent structure and check its own work?"; the delegation structure the decomposition creates lives in `relationship/`, and the communication that follows spawn lives in `communication/`.

## Owns
- The V-model use cases: recursive decomposition and per-turn self-verification.

## Excludes
- The delegation structure the decomposition creates — `relationship/`.
- The communication that follows spawn — `communication/`.

## Contents

<!-- pb:index:start -->
- **INFO-003** [Self-verify a turn](self-verify-a-turn.md) — Each action block analyzes its requirement, implements, verifies against the parents acceptance criteria, and reports
- **INFO-004** [Decompose a task recursively](decompose-a-task-recursively.md) — A parent writes delegation code that spawns encapsulated child workers and receives summaries plus artifact IDs
<!-- pb:index:end -->
