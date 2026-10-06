---
id: INFO-013
type: info
title: Broadcast one requirement to many children
summary: A parent spawns many children with the same requirement differing only in one parameter and picks among the results
date: 2026-10-05
status: current
---

# Broadcast one requirement to many children

- For a complex problem where the right approach is unknowable up front, a parent spawns many children with the same requirement, differing only in one parameter (`INFO-004`).
- All children run in parallel and are contained individually (`INFO-005`).
- Every child answers point-to-point with a summary plus artifact IDs (`INFO-006`); the parent picks among the returned results — an ensemble or parallel probe.
- The probe is exploratory: the parent commits to a direction only after seeing the results, probe-sense-respond.

## Owns
- One-to-many broadcast with parameterized copies of one requirement.

## Excludes
- Fan-out with distinct subtasks per child — `INFO-009`.
- In-task re-decomposition — `INFO-010`.
- The artifact contract the results ride on — `INFO-006`.
