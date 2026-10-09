"""The framework core: the control loop and its guarantees.

The runtime orchestrator, the per-agent persistent REPL, the in-code agent
surface, the worker loop with fabrication integrity, the event stream /
bus / completion dispatcher, the digest-observe context triggers, the rot
policy, and the message-rate caps watchdog — plus the directed-message
primitive (``Agent.send`` / ``Runtime.send``, decision 0015).

This package ships ZERO tools: nothing that gets installed into an agent
REPL namespace lives here (decisions 0014/0015/0016). The composed agent
world — the framework tools, the channels, the artifact store — is
:mod:`dhc.tooling`; the operator's side is :mod:`dhc.ui`; the composition
root is :mod:`dhc.wiring`. This package imports only the shared
vocabulary (:mod:`dhc.data`, :mod:`dhc.errors`).
"""
