---
id: 0015
type: decision
title: "Arch — Direct agent communication is framework; channels are tooling over the primitive"
date: 2026-10-09
status: accepted
---

# Arch — Direct agent communication is framework; channels are tooling over the primitive

## Context

Agents need to communicate with each other, not only with their parent via
spawn/settle. Before this decision that capability lived entirely in the
"channels": `Messenger` (direct point-to-point), `RoomManager` (shared
rooms), `EscalationChannel` (route up the parent chain), and
`OperatorQuestionChannel` (ask the operator) — implemented in
`src/dhc/ui/communication.py` with their namespace tools registered by the
*framework-side* `dhc.agent.tools.register_default_tools`.

Two facts motivated a re-evaluation:

1. **The substrate already existed, unnamed.** The core event bus routes
   events to per-agent streams by `event.agent_id` with
   persist-before-execute, FIFO, at-most-once delivery, and three
   independent read cursors (observe digest, `events` tool, caps
   watchdog). Receiver-addressed events already flow end-to-end into the
   receiving agent's *prompt* (digest → recent context). The runtime was a
   directed-mailbox machine that nobody called one.
2. **The one channel that should have used that substrate bypassed it.**
   `Messenger.send` emitted its `message_sent` event addressed to the
   *sender*, so recipients never saw direct messages in their stream; to
   compensate, the Messenger maintained a parallel, duplicate delivery
   mechanism — per-recipient FIFO queues, read flags, unread counts —
   that agents had to poll. (Escalation and operator answers, by
   contrast, were already receiver-addressed and flowed correctly.)

Meanwhile `0014` had drawn the core/tooling line for *persistence*, and its
refined classifier ("what does the core do with the concern — interpret it,
or carry it opaquely to operator-side persistence?") left the channels
straddling: they relay communication (framework-side flavor) but are
removable policies (tooling-side flavor). The classification was unstable.

## Decision

**Direct agent-to-agent communication is a framework primitive; every
channel is strict operator tooling composed over that primitive.**

1. **The core owns `Runtime.send(sender_id, recipient_id, body)`.** It
   emits a *receiver-addressed* `message_sent` event on the recipient's
   own event stream — the message rides the existing pipeline (digest,
   recent context, `events` tool) with **no channel tooling installed**.
   Delivery is at-next-step (seen at the next observe/turn boundary, like
   completions), not interruption — the control loop is untouched.
   `Agent.send(recipient_id, body)` is the thin in-code surface wrapper,
   bound in the **base namespace** as a core action (like `spawn` /
   `complete`), so a bare `Runtime` with zero tooling can do direct
   peer-to-peer messaging. The recipient must be a live agent
   (`ChannelError` otherwise); the sender is a free-form identity
   (agents pass their id; the operator passes `"operator"` — steering
   rides the same primitive). The body is a short value on the payload;
   large content belongs in an artifact reference (context encapsulation,
   principle 6). The receiving side is bounded by the existing
   `messages_per_step` cap, which now counts what its name says.
2. **The channels are tooling, giving the agent full control of its
   communication.** `Messenger`, `RoomManager`, `EscalationChannel`, and
   `OperatorQuestionChannel` move to `src/dhc/tooling/channels.py`;
   their tools (`room`, `messenger`, `escalate`, `ask_operator`, `post`,
   `channel_read`) move to `dhc.tooling.channel_tools` with their own
   `register_channel_tools` — the same registration mechanics as the
   artifact store tools (`0014`). The framework-side
   `register_default_tools` shrinks to the introspection/event reads
   (`list_tools`, `events`); its `ToolContext` loses the `channels` slot.
   Use, replace, or ignore each channel — the agent's communication
   capability beyond `send` is composition, not framework.
3. **The Messenger is rebuilt as a view, not a delivery mechanism.** It
   subscribes to the global feed and files receiver-addressed message
   events per recipient with read/unread sugar; its send delegates to the
   core primitive. Its parallel queues are deleted — the stream is the
   single source of truth, so with no Messenger installed, messages still
   arrive. Its constructor drops the `registry` and `sink` parameters
   (validation moved to the core; persistence is the event itself).
4. **Wiring is the only channel instantiator** (as it already was the only
   store instantiator, `0014`): the channels, their tools, the store, and
   the framework tools are composed in `wiring.build_runtime`.
5. **Boundary records:** a direct message is one receiver-addressed event
   and one `"messaged"` boundary record (the event's payload carries
   sender/body); the old separate `Message`-object sink path is removed.

The user's stated rationale, which this decision codifies: *the channels
should be strict tooling to allow the agent full control of its
communication* — the framework provides the minimal primitive, and every
richer pattern is a composed, replaceable policy.

## Consequences

- **Prompts change (intended):** recipients' digests and recent context now
  include direct messages. That is the point — guaranteed delivery into the
  recipient's awareness — bounded by the message-rate cap and the
  by-reference payload contract.
- **The sender's own stream no longer records the send** (the old
  `message_sent` was sender-addressed). Observability of sends is the
  operator's: the global event log and the `"messaged"` boundary record
  carry it.
- **`Operator.steer` rides the primitive:** the operator door steers via
  `runtime.send("operator", agent_id, message)` when the runtime provides
  `send` (fallbacks preserved for duck-typed fakes). And
  `Operator.run` now polls for settlement instead of blocking in `await_`,
  sweeping the question channel each pass, so an `ask_operator` question
  asked mid-run reaches the human before the run settles (INFO-023 — this
  wiring was dead before: no shipped entry point ever answered questions).
  The Terminal now prefers the wired `runtime.operator` (which carries the
  question channel) over constructing a bare one.
- **Dead code removed:** the legacy in-memory `room()` helper in
  `dhc.agent.agent` (superseded by `RoomManager`) and the `Message`-object
  sink path in `BoundarySink`.
- **Known wart, not widened here:** `ask_operator` is still
  fire-and-forget from the asking agent's perspective (it reads the answer
  as an event; there is no blocking wait). A `wait_for_answer` primitive
  would be new turn-scheduling machinery and is deliberately out of scope.
- **Supersedes part of `0014`'s consequences:** the "where the refined line
  falls" note in `0014` placed the channel tools in `dhc.agent.tools` as
  "framework-side composition". This decision moves them to `dhc.tooling`:
  the relay *primitive* is framework; the routing *patterns* are tooling.
  The refined classifier stands — sharpened, not contradicted: the core
  *interprets* the message event (routes it, caps it, persists it) rather
  than merely carrying it to operator-side storage; the channel policies
  are exactly the kind of replaceable concern the composition root exists
  to choose.
- **Guard test extended:** `tests/agent/test_core_tooling_boundary.py` now
  also asserts `send` is a core namespace name and the channel tool names
  are absent from the bare namespace.

## Rejected alternatives

- **A new `dhc.channels` package (a third home between core and
  tooling):** rejected — the user's line is cleaner: the core owns the
  primitive, *everything* above it is strict tooling. A middle package
  would re-create the framework-side/tooling ambiguity this decision
  resolves.
- **Keep the channels in `ui/communication.py` and only fix the
  addressing:** rejected — placement would still contradict the
  classification (agent-facing policies inside the operator interaction
  surface), and the Messenger's duplicate queues would survive.
- **Message bodies as artifact references (publish-then-send-the-id):**
  rejected as the *mandatory* shape — it couples messaging to store
  presence (breaking `0014`'s store-unaware core if required) and adds
  friction to trivial messages. Kept as guidance: large payloads belong
  in artifacts; `send` bodies are short values.
- **A blocking `send_and_wait` / interrupting mailbox (actor-turn
  semantics):** rejected — it would move message handling into the
  scheduler (the control loop), the one thing the at-next-step delivery
  model exists to avoid.
