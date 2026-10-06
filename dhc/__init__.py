"""dhc — Dynamic Harness Code.

A recursive agent runtime where every agent turn is one Python block executed
against a per-agent persistent REPL.

This package currently provides the foundation every other module builds on:
the core data models, the error hierarchy, and configuration. Later modules
(artifact_store, repl, event_stream, agent, runtime, llm, operator, cli) will
extend this surface.
"""

from .errors import (
    AgentCancelledError,
    AgentCrashedError,
    ArtifactNotFoundError,
    ChannelError,
    ConfigError,
    DhcError,
    TurnError,
    TurnTimeoutError,
)
from .models import (
    TERMINAL_STATES,
    AgentStatus,
    Artifact,
    Completion,
    CompletionLog,
    Event,
    EventKind,
    Message,
    Result,
    Room,
    ToolOutput,
    Turn,
    is_terminal,
)

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # errors
    "DhcError",
    "TurnError",
    "TurnTimeoutError",
    "AgentCancelledError",
    "AgentCrashedError",
    "ArtifactNotFoundError",
    "ChannelError",
    "ConfigError",
    # models
    "Artifact",
    "Result",
    "Event",
    "EventKind",
    "AgentStatus",
    "Completion",
    "CompletionLog",
    "ToolOutput",
    "Message",
    "Room",
    "Turn",
    "TERMINAL_STATES",
    "is_terminal",
]