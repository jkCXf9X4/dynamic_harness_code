"""Channel tools: the communication channel policies as REPL tools.

Operator tooling (decision 0015): direct agent-to-agent messaging is a
framework primitive (``Agent.send`` / ``Runtime.send``); every channel is
tooling composed ON TOP of it — a routing or read-state policy the agent
can use, replace, or ignore, keeping full control of its communication.
This module installs the channel tools (``room``, ``messenger``,
``escalate``, ``ask_operator``, ``post``, ``room_messages``,
``channel_read``) with the same
namespace-wrapping mechanics as :func:`dhc.tooling.register_artifact_tools`;
the composition root (``wiring.build_runtime``) is the caller.

The ``messenger`` tool is a per-agent facade: ``send`` delegates to the
framework primitive (``Runtime.send``); the read methods surface the shared
:class:`~dhc.tooling.channels.Messenger` view's inbox/read-state sugar.
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Any, Callable

from ..errors import ChannelError
from ..data.models import Event, Message, Room
from .channels import Messenger


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #


@dataclass
class ChannelContext:
    """The lightweight surface a channel tool receives — never the Agent.

    All collaborators are duck-typed so the channel tools work standalone
    (tests, REPL sessions) as well as fully wired:

    * ``runtime`` — anything exposing the supervision surface the tool
      needs (``get``); may be ``None``.
    * ``bus`` — anything with ``publish(event)`` (the event bus).
    * ``channels`` — a dict of named channel objects: ``messenger`` (the
      shared inbox view), ``rooms``, ``escalations``, ``questions``.
    """

    agent_id: str
    runtime: Any = None
    bus: Any = None
    channels: dict[str, Any] = field(default_factory=dict)

    # -- convenience accessors ----------------------------------------------

    @property
    def messenger(self) -> Any:
        """The shared Messenger view (or ``None`` when not wired)."""
        return self.channels.get("messenger")

    @property
    def rooms(self) -> Any:
        """The room manager (or ``None`` when not wired)."""
        return self.channels.get("rooms")

    @property
    def escalations(self) -> Any:
        """The escalation channel (or ``None`` when not wired)."""
        return self.channels.get("escalations")

    @property
    def questions(self) -> Any:
        """The operator-question channel (or ``None`` when not wired)."""
        return self.channels.get("questions")


# --------------------------------------------------------------------------- #
# Tool implementations (all take/return simple values)
# --------------------------------------------------------------------------- #


class _BoundMessenger:
    """A per-agent facade over the core send primitive + the inbox view.

    ``send`` delegates to the framework primitive (``Runtime.send``,
    decision 0015) — delivery is core, this facade is sugar. The read
    methods surface the shared Messenger view's read-state tracking.
    """

    def __init__(self, runtime: Any, view: Messenger, agent_id: str) -> None:
        self._runtime = runtime
        self._view = view
        self._agent_id = agent_id

    def send(self, recipient_id: str, body: str) -> Message:
        self._runtime.send(self._agent_id, recipient_id, body)
        return Message(sender_id=self._agent_id, recipient_id=recipient_id, body=body)

    def inbox(self) -> list[Message]:
        return self._view.inbox(self._agent_id)

    def read(self, message_id: str) -> Message | None:
        return self._view.read(self._agent_id, message_id)

    def unread_count(self) -> int:
        return self._view.unread_count(self._agent_id)


def _room(ctx: ChannelContext, room_name: str) -> Room:
    """Join (creating if needed) the shared room *room_name*; return a snapshot.

    The returned :class:`~dhc.models.Room` is a deep copy: the shared room
    object stays owned by the RoomManager, so membership, message history,
    and the posting gate (``ChannelError`` for non-members, event
    emission, sink persistence) cannot be bypassed by mutating a tool
    return value. Reads are always fresh — join again to see newer traffic.
    """
    if ctx.rooms is None:
        raise RuntimeError("no room manager wired into the tools layer")
    room = ctx.rooms.join(ctx.agent_id, room_name)
    return room.model_copy(deep=True) if hasattr(room, "model_copy") else room


def _post(ctx: ChannelContext, room_name: str, body: str) -> Message:
    """Post *body* to *room_name* as the calling agent."""
    if ctx.rooms is None:
        raise RuntimeError("no room manager wired into the tools layer")
    return ctx.rooms.post(ctx.agent_id, room_name, body)


def _room_messages(ctx: ChannelContext, room_name: str) -> list[Message]:
    """Return the room's traffic in post order WITHOUT joining (W3.7).

    A pure read: no membership side effect, no room creation. Raises
    ``ChannelError`` naming the room when the room is unknown (W3.10).
    """
    if ctx.rooms is None:
        raise RuntimeError("no room manager wired into the tools layer")
    return ctx.rooms.messages(room_name)


def _channel_read(
    ctx: ChannelContext, room_name: str | None = None, topic: str | None = None
) -> list[Message]:
    """Return the room's traffic in post order (advanced, W3.7).

    Deprecated alias of :func:`room_messages` — kept for compatibility.
    ``topic`` is a deprecated keyword alias for ``room_name`` (W3.4);
    passing it emits a ``DeprecationWarning``.
    """
    if topic is not None:
        warnings.warn(
            "channel_read(topic=...) is deprecated; use room_name=",
            DeprecationWarning,
            stacklevel=3,
        )
        room_name = topic
    if room_name is None:
        raise TypeError("channel_read() missing required argument: 'room_name'")
    if ctx.rooms is None:
        raise RuntimeError("no room manager wired into the tools layer")
    return ctx.rooms.messages(room_name)


def _escalate(ctx: ChannelContext, requirement: str, reason: str) -> Event:
    """Escalate an unreachable *requirement* up the parent chain."""
    if ctx.escalations is None:
        raise RuntimeError("no escalation channel wired into the tools layer")
    parent_id = getattr(ctx.runtime, "parent_id", None)
    if parent_id is None and ctx.runtime is not None:
        agent = ctx.runtime.get(ctx.agent_id)
        parent_id = getattr(agent, "parent_id", None)
    if parent_id is None:
        raise ChannelError("root agent has no parent to escalate to")
    return ctx.escalations.escalate(
        ctx.agent_id, parent_id, requirement, reason
    )


def _ask_operator(ctx: ChannelContext, question: str) -> str:
    """Ask the operator *question*; return the question id (W3.6).

    The returned id is the question event's ``payload["event_id"]`` — the
    handle the asker polls with ``answers(question_id)`` until the
    operator's answer text arrives, instead of excavating the consume-once
    ``events()`` cursor for the payload.
    """
    if ctx.questions is None:
        raise RuntimeError("no operator-question channel wired into the tools layer")
    event = ctx.questions.ask(ctx.agent_id, question)
    return str(event.payload["event_id"])


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

#: The canonical tool names installed by :func:`register_channel_tools`.
_CHANNEL_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "room",
        "messenger",
        "escalate",
        "ask_operator",
        "post",
        "channel_read",
        "room_messages",
    }
)


def _bind(ctx: ChannelContext) -> dict[str, Callable[..., Any]]:
    """Build the channel namespace callables bound to *ctx*.

    ``messenger`` is an object (the per-agent facade over the core send
    primitive plus the inbox view), not a callable — it is installed as a
    namespace value like the reference's tool objects, and only when the
    shared view is wired.
    """
    bound: dict[str, Any] = {}
    if ctx.messenger is not None:
        bound["messenger"] = _BoundMessenger(ctx.runtime, ctx.messenger, ctx.agent_id)
    bound.update(
        {
            "room": lambda room_name: _room(ctx, room_name),
            "escalate": lambda requirement, reason: _escalate(
                ctx, requirement, reason
            ),
            "ask_operator": lambda question: _ask_operator(ctx, question),
            "post": lambda room_name, body: _post(ctx, room_name, body),
            "room_messages": lambda room_name: _room_messages(ctx, room_name),
            "channel_read": lambda room_name=None, topic=None: _channel_read(
                ctx, room_name, topic
            ),
        }
    )
    return bound


def _register_surface_entries() -> None:
    """Register the channel-tool surface entries (idempotent, W1.2)."""
    from ..framework.surface import SurfaceEntry, default_registry

    default_registry.register(
        SurfaceEntry(
            name="room",
            fn=_room,
            doc="Join (creating if needed) a shared room; return a snapshot.",
            tier="core",
            call="room(room_name)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="messenger",
            fn=None,
            doc="Per-agent facade: send + inbox/read-state sugar.",
            tier="core",
            call="messenger.send(recipient_id, body)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="escalate",
            fn=_escalate,
            doc="Escalate to the parent: requirement + reason (two args).",
            tier="core",
            call="escalate(requirement, reason)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="ask_operator",
            fn=_ask_operator,
            doc="Ask the human operator a question; returns the question id.",
            tier="core",
            call="ask_operator(question)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="post",
            fn=_post,
            doc="Post a message to a room.",
            tier="core",
            call="post(room_name, body)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="room_messages",
            fn=_room_messages,
            doc="Read a room's traffic in post order without joining.",
            tier="core",
            call="room_messages(room_name)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="channel_read",
            fn=_channel_read,
            doc="Deprecated alias of room_messages (advanced).",
            tier="advanced",
        )
    )


def register_channel_tools(
    runtime: Any,
    bus: Any = None,
    channels: dict[str, Any] | None = None,
) -> None:
    """Install the channel tools as namespace callables on *runtime*.

    Same mechanics as ``dhc.tooling.framework_tools.register_default_tools``: W1.3
    appends a builder to the runtime's ordered, public namespace-builder
    chain (``runtime.register_namespace_builder``) so each agent's turn
    namespace gains the channel tools bound to that agent. The framework
    core is untouched: it keeps its slim base namespace; the channel
    tools are composed in here.

    *bus* is duck-typed (``publish(event)``); *channels* maps names to
    channel objects (``messenger`` — the shared inbox view, ``rooms``,
    ``escalations``, ``questions``). A channel value may be a plain object
    or a callable ``(agent_id) -> bound facade`` — the callable form
    resolves per agent at namespace-build time.
    """
    channels = dict(channels or {})
    names = set(getattr(runtime, "_installed_tool_names", ()))
    names.update(_CHANNEL_TOOL_NAMES)
    runtime._installed_tool_names = names

    _register_surface_entries()

    def build(agent: Any) -> dict:
        resolved: dict[str, Any] = {}
        for name, channel in channels.items():
            resolved[name] = channel(agent.id) if callable(channel) else channel
        ctx = ChannelContext(
            agent_id=agent.id,
            runtime=runtime,
            bus=bus,
            channels=resolved,
        )
        return _bind(ctx)

    runtime.register_namespace_builder(build, name="channel_tools")


__all__ = [
    "ChannelContext",
    "register_channel_tools",
]

# The channel-tool surface entries are registered at import time (W1.2):
# the registry must be complete before any runtime is wired.
_register_surface_entries()
