---
title: Selected IMPs
summary: Scoped candidates chosen for pursuit, awaiting decision records and adoption
---

# Selected IMPs

Candidates the product owner has picked and scoped. Ordering here is not a
schedule; adoption still runs through the change pipeline.

## Owns
- The selected-but-not-yet-adopted IMP queue.

## Excludes
- The pain and evidence behind each candidate, which lives in the IMP leaf.

## Contents

<!-- pb:index:start -->
- **INFO-024** [Resume an interrupted run from persisted state](resume-an-interrupted-run-from-persisted-state.md) — A dead runtime process loses every running hierarchy; candidate: per-agent checkpoints and a resume that rebuilds the run from persisted state
- **INFO-025** [Embed the runtime in a host process behind an API](embed-the-runtime-in-a-host-process-behind-an-api.md) — A host application can construct and drive the runtime through a committed API surface, decoupling the harness from any UI
- **INFO-026** [Compress a running agent's context](compress-a-running-agent-s-context.md) — Collapse accumulated context into a summary that leans on persisted artifacts, the committed remedy for detected context rot short of re-decomposition
- **INFO-027** [Trace a failure to its provenance without re-running](trace-a-failure-to-its-provenance-without-re-running.md) — A queryable trail tying each agent to its actions and artifacts, so a failure is diagnosed by reading records only
<!-- pb:index:end -->
