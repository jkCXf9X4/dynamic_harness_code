---
title: Operator use cases
summary: The operator converses with, steers, and observes the mesh through the root and the TUI
---

# Operator use cases

Use cases whose counterpart is the operator: the request enters at the root,
results return through the artifact tiers, and the operator steers mid-turn.

## Owns
- The operator-facing behaviors of a running mesh.

## Excludes
- Hosting, resuming, or embedding the runtime process itself — `run-the-runtime/`.

## Contents

<!-- pb:index:start -->
<!-- GENERATED FILE — do not edit. Regenerate with pb-registers. -->
- **INFO-017** [Converse with the operator](converse-with-the-operator.md) — The operator's request enters at the root agent and the root's result returns to the operator, the only door between human and mesh
- **INFO-022** [Chat continuously while subagents run](chat-continuously-while-subagents-run.md) — Operator messages keep flowing while subagents run, and a message sent mid-turn steers the root's current turn immediately
- **INFO-023** [Ask the operator a question](ask-the-operator-a-question.md) — Any agent can ask the operator a question; the question routes up the parent chain and the answer returns to the asking agent
- **INFO-028** [Minimalistic UI/TUI](drive-the-tui-from-persistent-files.md) — The operator's TUI is a minimal chat whose content and layout come from persistent files
<!-- pb:index:end -->
