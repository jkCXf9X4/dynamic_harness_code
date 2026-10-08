"""dhc error hierarchy.

All dhc-specific failures derive from :class:`DhcError` so callers can catch a
single base type; the subclasses distinguish the failure modes the runtime and
agent code must branch on.
"""


class DhcError(Exception):
    """Base class for all dhc errors."""


class TurnError(DhcError):
    """A coded action (turn) failed to execute or verify."""


class TurnTimeoutError(TurnError):
    """A turn exceeded its wall-clock budget (``max_turn_seconds``)."""


class AgentCancelledError(DhcError):
    """The agent was cancelled before reaching a terminal result."""


class AgentCrashedError(DhcError):
    """The agent's execution context crashed (subprocess/REPL died)."""


class ArtifactNotFoundError(DhcError):
    """An artifact id was referenced but no such artifact exists."""


class ChannelError(DhcError):
    """A messaging channel (direct, room, or settlement) misbehaved."""


class ConfigError(DhcError):
    """Invalid or missing configuration."""