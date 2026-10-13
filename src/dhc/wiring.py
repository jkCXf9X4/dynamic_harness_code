"""Wiring: build a fully-wired Runtime from the real committed modules.

The committed :class:`~dhc.runtime.Runtime` was written against lightweight
in-memory duck-types (``_MemoryEngine``, ``_MemoryBus``) with a topic-based
bus contract (``publish(topic, event)`` / ``drain(topic)``). The real
modules have richer contracts:

* :class:`~dhc.repl.ReplEngine.execute` returns a :class:`~dhc.models.Result`
  and never raises (failures are values, INFO-020), while the runtime expects
  a raising engine (it catches ``TurnTimeoutError`` / ``Exception``).
* :class:`~dhc.event_stream.EventBus.publish(event)` takes one argument and
  routes by ``event.agent_id``; the runtime calls ``publish(topic, event)``.

:func:`build_runtime` bridges these seams with small adapters and wires the
real modules together. It is the composition root and the ONLY place the
operator tooling (:mod:`dhc.tooling` — the artifact store and boundary log,
per decision 0014) is instantiated: the framework core is store-unaware and
the store adapter is attached to the runtime post-construction, like the
other wiring-level attributes.

* :class:`~dhc.repl.ReplEngine` — per-agent persistent REPL (INFO-050)
* :class:`~dhc.event_stream.EventBus` with the
  :class:`~dhc.tooling.BoundaryEventLog` as its persist sink (INFO-049)
* :class:`~dhc.event_stream.CompletionDispatcher` — at-most-once (INFO-046)
* :class:`~dhc.tooling.ArtifactStore` — content-addressed (INFO-006)
* the communication channels (Messenger, RoomManager, EscalationChannel,
  OperatorQuestionChannel) on the same bus — operator tooling (0015)
  composed over the core directed-message primitive (``Runtime.send``)
* the tools layer (:func:`dhc.tooling.framework_tools.register_default_tools` for the
  framework tools, :func:`dhc.tooling.register_channel_tools` for the
  channel tools, :func:`dhc.tooling.register_artifact_tools` for the store
  tools) — exposed as REPL namespace callables, composed in here (the
  composition root), not in the core runtime.
"""

from __future__ import annotations

import warnings
from pathlib import Path
from typing import Any, Callable, Optional

from .tooling import (
    ArtifactStore,
    BoundaryEventLog,
    BoundarySink,
    StoreAdapter,
)
from .tooling.artifact_tools import register_artifact_tools
from .tooling.channel_tools import register_channel_tools
from .tooling.channels import (
    EscalationChannel,
    Messenger,
    OperatorQuestionChannel,
    RoomManager,
)
from .data.config import get_settings
from .llm.driver import MockDriver, driver_from_settings
from .llm.llm import ContextRotDetector
from .errors import ChannelError, TurnError, TurnTimeoutError
from .framework.event_stream import CompletionDispatcher, EventBus
from .tooling.fabrication import fabrication_kit
from .ui.checkpoint import CheckpointStore
from .ui.operator import Operator
from .framework.repl import ReplEngine
from .framework.runtime import Runtime
from .tooling.framework_tools import register_default_tools


class _WiredBus:
    """Present the runtime's topic-based bus contract over the real modules.

    The committed runtime calls ``publish(topic, event)`` and ``drain(topic)``
    with topics ``events:<agent_id>`` and ``completions:<agent_id>``. This
    adapter routes:

    * ``events:*`` -> the real :class:`~dhc.event_stream.EventBus` (which
      persists to the boundary log via its sink, then routes to the agent's
      stream).
    * ``completions:*`` -> the real
      :class:`~dhc.event_stream.CompletionDispatcher` (at-most-once, FIFO per
      parent).
    """

    def __init__(self, bus: EventBus, dispatcher: CompletionDispatcher) -> None:
        self._bus = bus
        self._dispatcher = dispatcher

    def publish(self, topic: str, event: Any) -> None:
        if topic.startswith("events:"):
            self._bus.publish(event)
        elif topic.startswith("completions:"):
            parent_id = topic[len("completions:") :]
            self._dispatcher.enqueue(event, parent_id=parent_id)
        else:
            raise ValueError(f"unknown bus topic {topic!r}")

    def drain(self, topic: str) -> list:
        if topic.startswith("events:"):
            agent_id = topic[len("events:") :]
            return self._bus.stream_for(agent_id).drain()
        if topic.startswith("completions:"):
            agent_id = topic[len("completions:") :]
            return self._dispatcher.drain_for(agent_id)
        raise ValueError(f"unknown bus topic {topic!r}")

    def peek(self, topic: str) -> list:
        """Return the topic's events without consuming them (fan-out seam).

        Mirrors :meth:`drain` for the ``events:*`` topics only: the
        ``completions:*`` topics stay destructive (INFO-046 at-most-once).
        """
        if topic.startswith("events:"):
            agent_id = topic[len("events:") :]
            return self._bus.stream_for(agent_id).peek()
        raise ValueError(f"unknown bus topic {topic!r}")


class _ReplEngineAdapter:
    """Translate the ReplEngine's Result-returning contract into the
    runtime's raising contract.

    The committed runtime catches ``TurnTimeoutError`` (-> timeout terminal)
    and ``Exception`` (-> failed terminal) from ``engine.execute``. The real
    ReplEngine never raises: it returns a failed :class:`~dhc.models.Result`
    both when the code raised (contained, INFO-005) and when the agent
    deliberately called ``fail()``. This adapter re-raises only the former —
    a deliberate ``fail()`` leaves ``agent._last_result`` set, which the
    runtime reads and settles on; a raised exception leaves it ``None``, so
    the runtime's crash containment must see it.
    """

    def __init__(
        self,
        engine: ReplEngine,
        resolve_agent: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._engine = engine
        self._resolve_agent = resolve_agent

    def execute(
        self,
        agent_id: str,
        code: str,
        namespace: Optional[dict] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        result = self._engine.execute(agent_id, code, namespace, timeout)
        if result.ok:
            return result
        reason = result.reason or "turn failed"
        if "timed out" in reason:
            raise TurnTimeoutError(reason)
        agent = self._resolve_agent(agent_id) if self._resolve_agent else None
        if agent is not None and agent._last_result is not None:
            # The agent deliberately produced a result (complete/fail/cancel);
            # the runtime reads agent._last_result and settles accordingly.
            return result
        raise TurnError(reason)


def _extend_namespace(
    runtime: Runtime,
    bus: EventBus,
    messenger: Messenger,
    rooms: RoomManager,
    escalations: EscalationChannel,
    questions: OperatorQuestionChannel,
    store: Any,
) -> None:
    """Compose the tools layer onto the runtime's core namespace.

    The core :class:`~dhc.runtime.Runtime` builds the slim base namespace
    (agent, spawn, send, complete, fail, cancel, status, result, tool, bash,
    await_, poll, children_of) — ``send`` is the directed-message primitive
    itself (decision 0015). This composition root installs the framework
    tools (``list_tools``, ``events``) via
    :func:`dhc.tooling.framework_tools.register_default_tools`, the channel tools
    (rooms, escalation, operator questions, the messenger facade) via
    :func:`dhc.tooling.register_channel_tools` (decision 0015), the artifact
    store tools via :func:`dhc.tooling.register_artifact_tools` (decision
    0014), plus the driver factory (MockDriver / driver_from_settings)
    that action blocks use to spawn children.
    """
    register_default_tools(runtime, bus=bus)
    # The channel tools are operator tooling (decision 0015): policies over
    # the core send primitive, composed here so the agent controls which
    # communication patterns its stack carries.
    register_channel_tools(
        runtime,
        bus=bus,
        channels={
            "messenger": messenger,
            "rooms": rooms,
            "escalations": escalations,
            "questions": questions,
        },
    )
    # The store tools (publish, read_artifact, archive, list_artifacts) come
    # from the tooling layer (decision 0014) — same namespace-wrapping
    # mechanics, separate module, so the framework core stays store-unaware.
    register_artifact_tools(runtime, store=store, bus=bus)

    # W1.3: the wiring root's own additions (the driver factory names and
    # the fabrication kit) are the LAST builder in the ordered, public
    # chain — the same position the historical wrap chain gave them.
    def build(agent: Any) -> dict:
        ns: dict[str, Any] = {
            "MockDriver": MockDriver,
            "driver_from_settings": driver_from_settings,
        }
        # IMP-001 Step 2: the fabrication kit (default __runner + decide +
        # context + helpers) is injected into every agent's namespace. The
        # kit is installable and testable WITHOUT the pump (Step 3 rewrites
        # runtime.py): the default __runner is a workspace-citizen generator
        # that tests can drive directly through ReplEngine.advance.
        # IMP-001 Step 5 (D5): the guardrail surface is complete here —
        # (a) NORMATIVE parent-imposed constraints arrive as visible
        # context-in at delegation via spawn(..., namespace=...) (the
        # existing seam — no new injection channel); (b) OPERATIONAL
        # tripwires (caps, budgets) are evaluated by the pump between steps;
        # (c) REACTIONS ship as completion-style events on the parent's
        # stream. The kit's context.guardrails dict is the self-authored
        # store (ordinary workspace data, D2). The wired namespace injects a
        # FRESH kit with fresh state — the pump seeds state["_driver"] before
        # install and must NOT merge the kit with _build_namespace.
        kit = fabrication_kit(runtime, runtime.repl_engine, agent)
        ns.update(kit)
        return ns

    runtime.register_namespace_builder(build, name="wiring_kit")


class WiredRuntime(Runtime):
    """A :class:`~dhc.framework.runtime.Runtime` with every wiring-level
    decoration declared (W4.1).

    :func:`build_runtime` attaches the real modules (ReplEngine, EventBus,
    CompletionDispatcher, ArtifactStore, the communication channels, the
    operator door, the rot detector, and the operator's default
    :class:`~dhc.ui.checkpoint.CheckpointStore`) after construction. This
    subclass declares each of those decorations as a typed class-level
    annotation so the wired runtime is a typed, inspectable object: static
    checkers and ``hasattr`` both see the full surface, and the core
    :class:`Runtime` stays store/channel-unaware.

    ``artifact_store`` is the public read surface (the
    :class:`~dhc.tooling.StoreAdapter`). The historical
    ``artifact_store_real`` name is kept as a deprecated read-only property
    that forwards to ``artifact_store`` (the raw
    :class:`~dhc.tooling.ArtifactStore` is no longer exposed directly).
    """

    # Post-construction decorations attached by build_runtime (W4.1):
    # declared as annotations only — no assigned defaults, so a bare
    # WiredRuntime() is a plain Runtime until build_runtime wires it.
    messenger: Messenger
    rooms: RoomManager
    escalations: EscalationChannel
    questions: OperatorQuestionChannel
    dispatcher: CompletionDispatcher
    boundary_log: BoundaryEventLog
    bus: EventBus
    artifact_store: StoreAdapter
    operator: Operator
    mock: bool
    rot_detector: ContextRotDetector
    repl_engine: ReplEngine
    checkpoint_store: CheckpointStore

    @property
    def artifact_store_real(self) -> StoreAdapter:
        """The artifact store (deprecated name).

        .. deprecated::
            Use :attr:`artifact_store` (the :class:`~dhc.tooling.StoreAdapter`)
            instead. This property forwards to it and emits a
            :class:`DeprecationWarning`; it is kept as a shim until the
            remaining readers are migrated, then deleted in a later release.
        """
        warnings.warn(
            "WiredRuntime.artifact_store_real is deprecated; use "
            "WiredRuntime.artifact_store (the StoreAdapter) instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.artifact_store


def build_runtime(
    settings: Any = None,
    mock: bool = False,
    artifact_root: Any = None,
) -> WiredRuntime:
    """Construct a fully-wired :class:`WiredRuntime`.

    Wires the REAL modules: ReplEngine, EventBus (with BoundaryEventLog as
    the persist sink), CompletionDispatcher, ArtifactStore, and the
    communication channels (Messenger, RoomManager, EscalationChannel,
    OperatorQuestionChannel) — all on the same bus. The channels are exposed
    as ``runtime.messenger``, ``runtime.rooms``, ``runtime.escalations``,
    ``runtime.questions``; the operator door as ``runtime.operator``; the
    dispatcher as ``runtime.dispatcher``; the boundary log as
    ``runtime.boundary_log``; the store adapter as ``runtime.artifact_store``
    (the historical ``runtime.artifact_store_real`` name is a deprecated
    property forwarding to it) — wiring-level decorations attached after
    construction, the core never reads them. A default
    operator :class:`~dhc.ui.checkpoint.CheckpointStore` is attached under
    the artifact root as ``runtime.checkpoint_store`` (W6.1), so the
    terminal's ``/resume`` works out of the box.

    The artifact store and channels are installed into the agent namespace as
    REPL tools (publish, read_artifact, archive, list_artifacts, room,
    messenger, escalate, ask_operator, post, channel_read, list_tools,
    events) by :func:`dhc.tooling.register_artifact_tools`,
    :func:`dhc.tooling.register_channel_tools`, and
    :func:`dhc.tooling.framework_tools.register_default_tools` — the composition root,
    keeping the core (runtime + eventbus + the ``send`` primitive) slim and
    store/channel-unaware (decisions 0014/0015).

    *settings* defaults to the process-wide :func:`~dhc.config.get_settings`;
    *artifact_root* overrides the settings' artifact root; *mock* is kept for
    API compatibility (the mock path is chosen by the driver factory).
    """
    if settings is None:
        settings = get_settings()
    root = (
        Path(artifact_root)
        if artifact_root is not None
        else Path(settings.artifact_root)
    )
    store = ArtifactStore(root)
    boundary_log = BoundaryEventLog(root)
    sink = BoundarySink(boundary_log)
    bus = EventBus(sink=sink)
    dispatcher = CompletionDispatcher()
    store_adapter = StoreAdapter(store)

    runtime = WiredRuntime(
        engine=None,  # wired below (needs the runtime for agent resolution)
        event_bus=_WiredBus(bus, dispatcher),
        settings=settings,
        # Decision 0017: the default agent is composition — the birth kit
        # (default __runner__ + decide + context + helpers) is handed to
        # the runtime here; the pump drives whatever loop a workspace
        # holds but never authors it.
        kit_factory=fabrication_kit,
    )
    raw_engine = ReplEngine()
    engine = _ReplEngineAdapter(
        raw_engine, resolve_agent=runtime._agents.__getitem__
    )
    runtime.engine = engine
    # IMP-001 Step 2: expose the raw ReplEngine so the fabrication kit (and
    # tests driving the default __runner) can use install/advance/run_block
    # directly — the kit is installable and testable WITHOUT the pump.
    runtime.repl_engine = raw_engine

    messenger = Messenger(bus)
    rooms = RoomManager(bus, sink=sink)
    escalations = EscalationChannel(bus)
    questions = OperatorQuestionChannel(bus)

    runtime.messenger = messenger
    runtime.rooms = rooms
    runtime.escalations = escalations
    runtime.questions = questions
    runtime.dispatcher = dispatcher
    runtime.boundary_log = boundary_log
    runtime.bus = bus
    # The store is operator tooling (decision 0014): attached here as a
    # wiring-level decoration (adapter + raw store) — the core Runtime class
    # neither defines nor reads these attributes.
    runtime.artifact_store = store_adapter
    runtime.operator = Operator(runtime=runtime, question_channel=questions)
    runtime.mock = mock
    # INFO-021: activate the dormant context-rot detector — observe-only.
    # The per-agent fabrication kit forwards it to driver_from_settings so
    # LLMDriver.__call__'s existing per-block observation actually collects.
    runtime.rot_detector = ContextRotDetector()
    # W6.1: the operator's resumability store (decision 0016) is attached by
    # default under the artifact root, so the terminal's /resume works out
    # of the box. CheckpointStore.__init__ mkdirs its root, so it must live
    # under the runtime's workspace root (a tmp dir in tests, never CWD).
    runtime.checkpoint_store = CheckpointStore(root / "checkpoints")

    _extend_namespace(
        runtime, bus, messenger, rooms, escalations, questions, store_adapter
    )
    return runtime