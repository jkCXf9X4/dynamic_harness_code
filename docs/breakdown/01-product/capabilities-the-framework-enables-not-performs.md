---
id: INFO-074
type: info
title: Capabilities the framework enables, not performs
summary: Which scenario classes the framework supplies instruments for, and which workflow decisions stay with the agent
date: 2026-10-27
status: current
---

# Capabilities the framework enables, not performs

The framework supplies instruments.
The agent authors the workflow that uses them.
A concern is framework-owned only when a degraded agent could defeat it and take the mesh down (`INFO-053`).
Every other concern is agent-owned policy and composition.

## Scenario classes

- **Loop shape.**
  - Framework supplies: a pump that steps the loop one yield window at a time (`INFO-037`, `INFO-062`).
  - Agent owns: the loop itself, its cadence, and how the next action is chosen (`INFO-050`).
- **Context economy and encapsulation.**
  - Framework supplies: content-addressed artifacts with disclosure tiers (`INFO-006`).
  - Agent owns: what it pulls, what it hands down, and when (`INFO-004`).
  - Encapsulation is a delegation choice, not a framework filter.
- **Context rot.**
  - Framework supplies: runtime-owned detection between agent actions (`INFO-021`).
  - Agent owns: the policy half, threshold and reaction, as ordinary workspace data (`INFO-053`).
  - Parent owns: its own reaction to a degraded child (`INFO-061`).
  - Detection stays runtime-owned because a degrading agent must not be able to skip its own signal.
- **Capability growth.**
  - Framework supplies: Python, the REPL namespace, and the artifact store (`INFO-007`, `INFO-050`).
  - Agent owns: the tools it writes and keeps in its workspace.
- **Waiting and cooperation.**
  - Framework supplies: parking, completion dispatch, and directed delivery (`INFO-047`, `INFO-054`).
  - Agent owns: whether it awaits, polls, or sleeps (`INFO-053`).
- **Verification.**
  - Framework supplies: settlement and the event trail (`INFO-046`, `INFO-027`).
  - Agent owns: the acceptance checks it writes against its requirement (`INFO-003`).

## Test for a new scenario

Ask two questions in order.
Could a degraded agent defeat this and take the mesh down? If yes, it is runtime-owned (`INFO-053`).
Otherwise the framework exposes instruments and the agent writes the policy.
A framework feature that absorbs an agent-owned decision is misplaced.

## Owns
- The functional split: which scenario classes the framework enables, and which workflow decisions stay with the agent.

## Excludes
- The mechanical split, who enforces what — `INFO-053`.
- The boundary of the framework core — `INFO-054`.
- Scenario steps and observable outcomes — the Product use-case leaves, for example `INFO-021`.
- Implementation of any instrument — the Architecture layer.
