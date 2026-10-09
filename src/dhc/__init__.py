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

Layout (src layout, REV 3 — decision 0016: the framework/composition split
is the folder hierarchy itself):

    framework/  THE FRAMEWORK — the control loop and its guarantees:
                runtime, loop, agent surface, per-agent REPL, event
                stream/bus/completion dispatcher, context triggers, rot
                policy, caps watchdog, integrity — plus the directed-message
                primitive (``send``, 0015). Ships ZERO tools: nothing that
                gets installed into an agent REPL namespace lives here.
                Depends only on data/ and errors/.
    tooling/    THE AGENT'S COMPOSED WORLD — everything installed into agent
                REPL namespaces beyond the core actions: the framework
                tools (list_tools, events), the communication channels and
                their tools, the artifact store and its tools, and the
                adapters bridging them onto runtime seams (0014/0015/0016).
                One-way dependent on the framework.
    ui/         THE OPERATOR'S SIDE — the operator door, the interactive
                terminal, the operator's review files (state) and
                resumability store (checkpoint, 0012).
    llm/        provider plumbing (llm, driver, prompts, fabrication)
    data/       shared vocabulary both sides import (models, config, trace)
    benchmark/  unchanged subpackage
    wiring.py   THE COMPOSITION ROOT — the only module that imports both
                framework and tooling (and ui)
    cli.py, errors.py  entry point; cross-cutting error hierarchy
"""

from . import (
    benchmark,
    cli,
    data,
    errors,
    framework,
    llm,
    tooling,
    ui,
    wiring,
)
from .framework.agent import Agent, AgentHandle, ToolResult, bash
from .tooling.channels import (
    EscalationChannel,
    Messenger,
    OperatorQuestionChannel,
    RoomManager,
)
from .data.config import Settings, get_settings, load_settings
from .llm.driver import DEFAULT_SCRIPT, LLMDriver, MockDriver, driver_from_settings
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
from .framework.event_stream import CompletionDispatcher, EventBus, EventStream
from .llm.llm import ContextRotDetector, LLMClient, MockLLM, RotReport
from .data.models import (
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
from .ui.operator import ChatSession, DefaultDriver, Operator
from .framework.repl import ReplEngine
from .framework.runtime import Runtime
from .wiring import build_runtime

__version__ = "0.1.0"

__all__ = [
    "__version__",
    # subpackages / top-level modules
    "agent",
    "benchmark",
    "cli",
    "data",
    "errors",
    "llm",
    "tooling",
    "ui",
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
