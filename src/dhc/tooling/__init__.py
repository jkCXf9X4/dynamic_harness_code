"""The agent's composed world: everything installed into agent REPLs.

Decisions 0014/0015 drew the boundary; decision 0016 makes it the folder
hierarchy: the framework (``dhc.framework``) ships zero tools — this
package is everything an agent gets in its REPL namespace beyond the core
actions, composed onto the runtime by the composition root
(``wiring.build_runtime``) and one-way dependent on the framework:

* the default agent — the fabrication kit a workspace is born with
  (default ``__runner`` + ``decide`` + context + helpers), handed to the
  runtime via ``Runtime(kit_factory=...)`` —
  :mod:`dhc.tooling.fabrication` (decision 0017: the framework owns the
  pump and the runner contract, not the loop's content)
* the framework-surface tools (``list_tools``, ``events``) —
  :mod:`dhc.tooling.framework_tools`
* the communication channels and their tools —
  :mod:`dhc.tooling.channels` / :mod:`dhc.tooling.channel_tools`
* the artifact store, the boundary log, the store tools, and the adapters
  bridging them onto runtime seams — :mod:`dhc.tooling.artifact_store` /
  :mod:`dhc.tooling.artifact_tools` / :mod:`dhc.tooling.adapters`

The framework never imports this package; the composition root is the
only instantiator.
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
from .fabrication import (
    DEFAULT_RUNNER_SOURCE,
    FABRICATION_NAMES,
    FabricationContext,
    fabrication_kit,
)
from .framework_tools import ToolContext, register_default_tools

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
    "DEFAULT_RUNNER_SOURCE",
    "FABRICATION_NAMES",
    "FabricationContext",
    "fabrication_kit",
    "ToolContext",
    "register_default_tools",
]
