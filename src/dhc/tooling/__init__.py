"""Operator tooling: persistence, channels, and their namespace tools.

The framework core (``dhc.agent``) knows artifacts only as opaque ids and the
``artifact_published`` event kind (decision 0014), and knows communication
only as the directed-message primitive (``Runtime.send``, decision 0015).
Everything composed on top of those contracts lives here: the
content-addressed store, the boundary event log, the communication channel
policies (rooms, escalation, operator questions, the inbox view), the
adapters bridging them onto the runtime's seams, and the namespace tools
that expose them to agents. The composition root (``wiring.build_runtime``)
is the only place this package is instantiated; the framework never
imports it.
"""

from .adapters import BoundarySink, StoreAdapter
from .artifact_store import (
    BOUNDARY_EVENT_KINDS,
    ArtifactStore,
    BoundaryEventLog,
)
from .artifact_tools import register_artifact_tools
from .channels import (
    EscalationChannel,
    Messenger,
    OperatorQuestionChannel,
    RoomManager,
)
from .channel_tools import register_channel_tools

__all__ = [
    "ArtifactStore",
    "BoundaryEventLog",
    "BOUNDARY_EVENT_KINDS",
    "StoreAdapter",
    "BoundarySink",
    "register_artifact_tools",
    "Messenger",
    "RoomManager",
    "EscalationChannel",
    "OperatorQuestionChannel",
    "register_channel_tools",
]
