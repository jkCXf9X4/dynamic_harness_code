"""The framework core: the control loop and its guarantees.

The runtime orchestrator, the per-agent persistent REPL, the in-code agent
surface, the worker pump with fabrication integrity, the event stream /
bus / completion dispatcher, the digest-observe context triggers, the rot
policy, and the message-rate caps watchdog — plus the directed-message
primitive (``Agent.send`` / ``Runtime.send``, decision 0015).

Decision 0017 — the framework owns the PUMP, not the loop: the pump
(drives whatever ``__runner`` a workspace holds), the runner contract
(compile / install / re-install / re-seed), and the yield vocabulary
(``Await`` / ``Poll`` / ``Sleep``) are framework; the loop's content —
the default agent, the fabrication kit a workspace is born with — is
composed tooling (``dhc.tooling.fabrication``) handed in via
``Runtime(kit_factory=...)`` at the composition root.

This package ships ZERO tools: nothing that gets installed into an agent
REPL namespace lives here (decisions 0014/0015/0016). The composed agent
world — the framework tools, the channels, the artifact store — is
:mod:`dhc.tooling`; the operator's side is :mod:`dhc.ui`; the composition
root is :mod:`dhc.wiring`. This package imports only the shared
vocabulary (:mod:`dhc.data`, :mod:`dhc.errors`) — never tooling, never
the operator surface, never the provider plumbing (:mod:`dhc.llm`).
"""
