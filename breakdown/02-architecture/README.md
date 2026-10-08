---
title: Architecture
summary: The organizing design — how the dhc runtime's parts fit and interact
---

# Architecture

The organizing design: how the dhc runtime's parts fit and interact. Facts here answer "how is the runtime organized?"; what the runtime promises lives one layer up in Product, and the concrete materialization lives one layer down in Implementation. The committed architecture decisions live in `decisions/README.md` — dated history, one choice per record. The `## Contents` holds the harness's internal organization — the machinery behind delegation, each agent's own execution, and the boundary event log; the public-interface commitments live one layer up in Product.

## Owns
- How the parts fit and interact: agent concurrency placement, completion dispatch, cancellation delivery, event-stream resolution, and the boundary event log's data model.
- How the harness organizes work: delegation from parents, peer exchange, and each agent's own execution.

## Excludes
- What the runtime promises its users and integrators — one layer up in Product.
- Specific files, scripts, and configs — one layer down in Implementation.

## Contents

<!-- pb:index:start -->
- **INFO-037** [The kernel made real — the turn engine as a workspace-owned resumable generator](the-kernel-made-real.md) — The turn engine is made real as a workspace-owned, agent-authored resumable generator that the runtime pumps one yield-window at a time under a small hard-gate layer — the kernel in user space
- **INFO-038** [Run each agent in its own thread or process](run-each-agent-in-its-own-thread-or-process.md) — Every agent executes in its own thread-or-process unit, isolated from the runtime process and from every other agent
- **INFO-040** [Stop a cancelled child's worker](stop-a-cancelled-child-s-worker.md) — A parent's cancel request terminates the child's worker, and the child settles as cancelled with its partial work discarded
- **INFO-047** [Dispatch child completions between parent actions](dispatch-child-completions-between-parent-actions.md) — The runtime-owned queue and dispatcher carrying child completions to the parent — one event per settled child, callbacks between the parent's own actions
- **INFO-048** [Resolve the event stream outside agent code](resolve-the-event-stream-outside-agent-code.md) — Runtime-owned resolution machinery — the general event loop polls registered streams outside agent action code, and the turn engine settles each channel persist-before-execute, at most once, ensure-terminal
- **INFO-049** [Boundary event log](boundary-event-log.md) — The provenance trail's data model — five boundary events with causal ids, payloads traced by reference, greppable records
<!-- pb:index:end -->
