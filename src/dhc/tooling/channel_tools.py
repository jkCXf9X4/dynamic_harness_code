"""Channel tools: the communication channel policies as REPL tools.

Operator tooling (decision 0015): direct agent-to-agent messaging is a
framework primitive (``Agent.send`` / ``Runtime.send``); every channel is
tooling composed ON TOP of it — a routing or read-state policy the agent
can use, replace, or ignore, keeping full control of its communication.
This module installs the channel tools (``room``, ``messenger``,
``escalate``, ``ask_operator``, ``post``, ``channel_read``) with the same
namespace-wrapping mechanics as :func:`dhc.tooling.register_artifact_tools`;
the composition root (``wiring.build_runtime``) is the caller.

The ``messenger`` tool is a per-agent facade: ``send`` delegates to the
framework primitive (``Runtime.send``); the read methods surface the shared
:class:`~dhc.tooling.channels.Messenger` view's inbox/read-state sugar.
"""

from __future__ import annotations

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


def _room(ctx: ChannelContext, name: str) -> Room:
    """Join (creating if needed) the shared room *name*; return it."""
    if ctx.rooms is None:
        raise RuntimeError("no room manager wired into the tools layer")
    return ctx.rooms.join(ctx.agent_id, name)


def _post(ctx: ChannelContext, room_name: str, body: str) -> Message:
    """Post *body* to *room_name* as the calling agent."""
    if ctx.rooms is None:
        raise RuntimeError("no room manager wired into the tools layer")
    return ctx.rooms.post(ctx.agent_id, room_name, body)


def _channel_read(ctx: ChannelContext, topic: str) -> list[Message]:
    """Return the room's traffic in post order (empty for unknown rooms)."""
    if ctx.rooms is None:
        raise RuntimeError("no room manager wired into the tools layer")
    return ctx.rooms.messages(topic)


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


def _ask_operator(ctx: ChannelContext, question: str) -> Event:
    """Ask the operator *question* as the calling agent."""
    if ctx.questions is None:
        raise RuntimeError("no operator-question channel wired into the tools layer")
    return ctx.questions.ask(ctx.agent_id, question)


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
            "room": lambda name: _room(ctx, name),
            "escalate": lambda requirement, reason: _escalate(
                ctx, requirement, reason
            ),
            "ask_operator": lambda question: _ask_operator(ctx, question),
            "post": lambda room_name, body: _post(ctx, room_name, body),
            "channel_read": lambda topic: _channel_read(ctx, topic),
        }
    )
    return bound


def register_channel_tools(
    runtime: Any,
    bus: Any = None,
    channels: dict[str, Any] | None = None,
) -> None:
    """Install the channel tools as namespace callables on *runtime*.

    Same mechanics as ``dhc.tooling.framework_tools.register_default_tools``: the
    runtime's namespace builder (``_build_namespace``) is wrapped so each
    agent's turn namespace gains the channel tools bound to that agent. The
    framework core is untouched: it keeps its slim base namespace (with the
    ``send`` primitive); the channel policies are composed in here.

    *bus* is duck-typed (``publish(event)``); *channels* maps names to
    channel objects (``messenger`` — the shared inbox view, ``rooms``,
    ``escalations``, ``questions``). A channel value may be a plain object
    or a callable ``(agent_id) -> bound facade`` — the callable form
    resolves per agent at namespace-build time.
    """
    channels = dict(channels or {})
    original = getattr(runtime, "_build_namespace", None)
    names = set(getattr(runtime, "_installed_tool_names", ()))
    names.update(_CHANNEL_TOOL_NAMES)
    runtime._installed_tool_names = names

    def build(agent: Any) -> dict:
        ns = original(agent) if original is not None else {}
        resolved: dict[str, Any] = {}
        for name, channel in channels.items():
            resolved[name] = channel(agent.id) if callable(channel) else channel
        ctx = ChannelContext(
            agent_id=agent.id,
            runtime=runtime,
            bus=bus,
            channels=resolved,
        )
        ns.update(_bind(ctx))
        return ns

    runtime._build_namespace = build  # type: ignore[method-assign]


__all__ = [
    "ChannelContext",
    "register_channel_tools",
]
