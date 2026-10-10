---
id: INFO-054
type: info
title: The core boundary — what the framework core knows
summary: The boundary orthogonal to the control split: the framework core carries only what the control loop needs to be correct plus the directed-message primitive; everything that persists, observes, or renders state is operator tooling composed around it
date: 2026-10-09
status: current
---

# The core boundary — what the framework core knows

The control split (`INFO-053`) answers **who enforces** (agent vs runtime).
This boundary is orthogonal to it, fixed by `AD-008` and refined by `AD-009`:
**what the framework core carries**. The core owns only what the control loop
needs to be correct — the guarantees listed under runtime control in
`INFO-053` — plus the directed-message primitive: `Runtime.send` emits a
receiver-addressed `message_sent` event on the recipient's own stream, so a
direct message is guaranteed to reach the recipient's awareness (digest,
recent context, `events` tool) with no channel installed. Everything that
persists, observes, or renders state (the artifact store, the boundary log,
operator viewers) — and, since `AD-009`, every communication *policy* (rooms,
escalation routing, operator questions, the inbox read-state view) — is
operator tooling: composed at the composition root, one-way dependent on the
core, and removable without changing what the core guarantees. The agent's
communication beyond the primitive is its own composition choice.
Removability is the entry condition for composition, not the verdict — the
engine is removable and framework. The classifier is what the core does with
the concern: data it only carries opaquely, so someone can persist, observe,
or render it, is tooling; semantics it interprets — or the directed-message
relay itself — is framework. The artifact contract is the worked example: its
*vocabulary* — the content-addressed `Artifact` model, the disclosure tiers,
the `artifact_published` event — is framework; its *medium*, the store holding
the bodies, is tooling. The agent loop is the second: the pump, the runner
contract (compile, install, re-install, re-seed), and the yield vocabulary
are framework; the default agent — the fabrication kit a workspace is born
with, default `__runner__` and `decide` included — is composed tooling
(`dhc.tooling.fabrication`, handed in via `Runtime(kit_factory=...)` at the
composition root, `AD-011`). The runtime guarantees a loop exists and enforces
around it; what the loop does is the agent's.

## Owns
- The framework/tooling boundary: what the framework core carries versus the
  operator tooling composed around it, and the classifier that separates them.

## Excludes
- The control split this boundary is orthogonal to — `INFO-053`.
- How the boundary is implemented — the architecture layer.
