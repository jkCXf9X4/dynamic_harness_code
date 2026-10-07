"""dhc — Dynamic Harness Code.

A recursive agent runtime where every agent turn is one Python block executed
against a per-agent persistent REPL (ISO 15288 V-model discipline: analyze ->
decompose -> delegate -> verify -> synthesize -> terminate).

The package is fully wired: the core models, the per-agent REPL, the
runtime-owned event bus and completion dispatcher, the content-addressed
artifact store and boundary event log, the agent surface, the runtime
orchestrator, the LLM client and drivers, the communication channels, the
operator door, the minimal CLI, and the wiring that binds them all together.

Importable without an API key: the mock path (MockDriver / MockLLM) is the
documented test and demo path; the real LLM path activates only when
``OPENAI_API_KEY`` is set.
"""

from . import (
    agent,
    artifact_store,
    cli,
    communication,
    config,
    driver,
    errors,
    event_stream,
    llm,
    models,
    operator,
    repl,
    runtime,
    wiring,
)
from .agent import Agent, AgentHandle, ToolResult, bash, room
from .artifact_store import BOUNDARY_EVENT_KINDS, ArtifactStore, BoundaryEventLog
from .communication import (
    EscalationChannel,
    Messenger,
    OperatorQuestionChannel,
    RoomManager,
)
from .config import Settings, get_settings, load_settings
from .driver import DEFAULT_SCRIPT, LLMDriver, MockDriver, driver_from_settings
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
from .event_stream import CompletionDispatcher, EventBus, EventStream
from .llm import ContextRotDetector, LLMClient, MockLLM, RotReport
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
from .operator import ChatSession, DefaultDriver, Operator
from .repl import ReplEngine
from .runtime import Runtime
from .wiring import build_runtime

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # modules
    "agent",
    "artifact_store",
    "cli",
    "communication",
    "config",
    "driver",
    "errors",
    "event_stream",
    "llm",
    "models",
    "operator",
    "repl",
    "runtime",
    "wiring",
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
    # agent surface
    "Agent",
    "AgentHandle",
    "ToolResult",
    "bash",
    "room",
    # artifact store
    "ArtifactStore",
    "BoundaryEventLog",
    "BOUNDARY_EVENT_KINDS",
    # event stream
    "EventStream",
    "EventBus",
    "CompletionDispatcher",
    # repl
    "ReplEngine",
    # runtime
    "Runtime",
    # llm
    "LLMClient",
    "MockLLM",
    "ContextRotDetector",
    "RotReport",
    # drivers
    "LLMDriver",
    "MockDriver",
    "DEFAULT_SCRIPT",
    "driver_from_settings",
    # communication
    "Messenger",
    "RoomManager",
    "EscalationChannel",
    "OperatorQuestionChannel",
    # operator
    "Operator",
    "ChatSession",
    "DefaultDriver",
    # config
    "Settings",
    "get_settings",
    "load_settings",
    # wiring
    "build_runtime",
]