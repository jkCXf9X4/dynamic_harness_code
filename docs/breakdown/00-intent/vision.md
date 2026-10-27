---
id: INFO-001
type: info
title: VISION
summary: Mission, the bet and its disproof, commitments, precedence order, non-goals, success criteria, and accepted costs
date: 2026-10-27
status: current
---

# VISION

- **Mission.**
  - dhc is a recursive agent runtime.
  - Executable Python is the action space: every agent turn is one code block.
  - The runtime executes the block and guarantees the mesh survives the agent.
- **Audience.**
  - This leaf settles maintainer architecture calls.
  - It is the arbiter when two design options both look defensible.
- **Bet.**
  - One expressive code block per turn beats several tool-call turns on cost per resolved task, at equal or better quality.
  - Expressiveness is the mechanism: loops, fan-out, transforms, and error handling fit inside one action.
  - Fresh-context corollary: decomposed workers beat one long monolith.
  - The anchor is ~3K delegation overhead against >15K context rot, a claim under test rather than a measured result.
  - The bet is refuted when a tool-call agent matches quality at no higher cost on the reference set (`INFO-069`).

## Commitments

A commitment changes only when a decision record supersedes it.
`hard` marks the mesh-survival core.

- **C1 (hard) Mesh survival.** Settlement, containment, ceiling caps, and cancellation are runtime behavior (`INFO-053`).
- **C2 (hard) Containment.** A failed, hung, or runaway agent settles failed; the workspace is the blast radius (`INFO-005`). The container is the outer boundary (`INFO-008`).
- **C3 One action per turn.** A turn is one Python block that may loop, fan out, transform, and handle its own errors (`INFO-002`).
- **C4 Few turns.** Fewer expressive turns beat many narrow steps on cost and quality.
- **C5 Fresh context.** Work crosses agents as content-addressed ids and summaries, never as full bodies (`INFO-006`, `INFO-004`).
- **C6 Immutable artifacts.** Artifacts are content-addressed and tiered; an id proves the content (`INFO-006`, `AD-008`).
- **C7 Agent-owned loop.** The loop is workspace code, pumped one step at a time, seeded as an editable fabrication (`INFO-037`, `AD-011`).
- **C8 Enabling, not performing.** The framework supplies instruments; the agent authors policy and workflow (`INFO-074`).
- **C9 Small core, operator medium.** The core owns loop correctness and directed messaging; rooms, escalation, and rendering sit outside it (`INFO-054`).
- **C10 V per turn.** Each turn analyzes its requirement, implements, verifies against parent criteria, and reports (`INFO-003`).

## Precedence

When commitments conflict, the higher line wins.

1. Mesh survival over agent freedom (`INFO-053`).
2. Containment over visibility into the failure.
3. Fresh context over thread continuity.
4. Few turns over per-step granularity.
5. Agent-owned workflow over framework convenience (`INFO-074`).
6. Visible state over hidden mechanism (`INFO-053`).
7. Operator tooling outside the core, never inside (`INFO-054`).

## Non-goals

- **No model work.** dhc does not train, fine-tune, or rank models.
- **No tool registry.** Capabilities are agent-authored, not curated (`INFO-007`).
- **No workflow engine.** There is no declarative graph; the loop is code (`INFO-037`).
- **No prompt framework.** Prompt assembly is a workspace function (`INFO-053`).
- **No multi-tenant service.** One operator door per mesh (`INFO-017`).
- **No untrusted-code sandbox.** The container is the security boundary (`INFO-008`).

## Success criteria

All of these must hold on the reference set (`INFO-068`).

- **Cost.** Tokens per resolved task stay below the tool-call baseline (`INFO-069`).
- **Quality.** Task success equals or beats that baseline.
- **Turn count.** Turns per resolved task stay lower than the baseline.
- **Delegation overhead.** Overhead stays below the parent context it saves.
- **Containment.** No single agent failure degrades the mesh.
- **Disproof stands.** A failed bet ends the direction; framework policy is not added to rescue it.

## Costs accepted

- **Control flow is not reproducible.** The loop is agent code; the artifact and event trail carries the audit (`INFO-037`, `INFO-027`).
- **Trust surface inside the container.** Agent code is arbitrary Python (`INFO-072`).
- **Review cost.** Behaviour lives in code and artifacts, not in configuration.
- **Onboarding cost.** Defaults are starting points to edit, not a stable abstraction (`AD-011`).
- **Weaker static guarantees.** Guarantees are runtime gates, not types.

## Inspirations

- **dynamic_harness.** Carries V-model discipline, encapsulation, and context economics, not tool calls.
- **CodeAct.** Executable code actions elicit better agents.
- **ISO/IEC 15288.** V-model and system breakdown structure.
- **Actor model.** Private state, message passing, supervision.
- **Bazel and Nix.** Immutable artifacts and reproducibility.

## Owns
- The substrate direction: mission, bet, commitments, precedence, non-goals, success criteria, and accepted costs.

## Excludes
- Power distribution between agent and platform — `INFO-052`.
- The control split detail — `INFO-053`.
- The core boundary — `INFO-054`.
- Which workflows stay with the agent — `INFO-074`.
- Promised behavior and scenarios — the Product layer.
- Mechanism, shape, and defaults — the Architecture layer.
