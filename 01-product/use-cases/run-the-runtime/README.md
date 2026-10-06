---
title: Run the runtime
summary: Host, resume, and embed the runtime process as a whole, from outside the agent mesh
---

# Run the runtime

Use cases whose subject is the runtime process itself rather than any agent in
a running mesh: stand it up in a container, rebuild it after process death,
or embed it behind an API.

## Owns
- Acting on the runtime as a unit.

## Excludes
- What happens inside a running mesh — the other groups.

## Contents

<!-- pb:index:start -->
- **INFO-008** [Host the runtime in a container](host-the-runtime-in-a-container.md) — An operator runs the dhc runtime inside Docker or Podman as the outer security boundary
- **INFO-024** [Resume an interrupted run from persisted state](resume-an-interrupted-run-from-persisted-state.md) — A dead runtime process loses every running hierarchy; candidate: per-agent checkpoints and a resume that rebuilds the run from persisted state
- **INFO-025** [Embed the runtime in a host process behind an API](embed-the-runtime-in-a-host-process-behind-an-api.md) — A host application can construct and drive the runtime through a committed API surface, decoupling the harness from any UI
<!-- pb:index:end -->
