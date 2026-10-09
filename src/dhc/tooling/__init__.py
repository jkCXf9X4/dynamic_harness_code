"""Operator tooling: artifact persistence, boundary logging, store tools.

The framework core (``dhc.agent``) knows artifacts only as opaque ids and the
``artifact_published`` event kind (decision 0014). Everything that persists
them — the content-addressed store, the boundary event log, the adapters
bridging them onto the runtime's seams, and the store-backed namespace tools
— lives here. The composition root (``wiring.build_runtime``) is the only
place this package is instantiated; the framework never imports it.
"""

from .adapters import BoundarySink, StoreAdapter
from .artifact_store import (
    BOUNDARY_EVENT_KINDS,
    ArtifactStore,
    BoundaryEventLog,
)
from .artifact_tools import register_artifact_tools

__all__ = [
    "ArtifactStore",
    "BoundaryEventLog",
    "BOUNDARY_EVENT_KINDS",
    "StoreAdapter",
    "BoundarySink",
    "register_artifact_tools",
]
