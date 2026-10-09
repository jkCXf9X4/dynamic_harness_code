"""The tools layer: communication channels and events as REPL tools.

The architectural goal (refactor scoping brief §c6/§c8): the CORE is only
``dhc/runtime.py`` + ``dhc/event_stream.py``. The artifact store and the
communication channels are *not* core collaborators — they are REPL-executed
Python tools: namespace callables developed separately from the core and
installed by registration functions. The channel and events tools live here
(framework-side); the artifact store tools (publish, read_artifact, archive,
list_artifacts) live in :mod:`dhc.tooling.artifact_tools` — the store itself
is operator tooling, not framework (decision 0014).

Tools receive a lightweight :class:`ToolContext` (agent_id + duck-typed
collaborators), never the :class:`~dhc.agent.Agent` itself — mirroring the
reference project's ``core/tools/`` separation. The runtime stays slim: its
base namespace contains only core names; everything else is composed in by
``dhc/wiring.py`` via the registration functions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..errors import ChannelError
from ..data.models import Event, Message, Room


# --------------------------------------------------------------------------- #
# ToolContext
# --------------------------------------------------------------------------- #


@dataclass
class ToolContext:
    """The lightweight surface a tool receives — never the Agent.

    All collaborators are duck-typed so the tools layer works standalone
    (tests, REPL sessions) as well as fully wired:

    * ``runtime`` — anything exposing the supervision surface the tool needs
      (e.g. ``children_of``, ``get``); may be ``None``.
    * ``bus`` — anything with ``publish(event)`` (the event bus).
    * ``channels`` — a dict of named channel facades: ``messenger``,
      ``rooms``, ``escalations``, ``questions``.

    The artifact store deliberately has NO slot here (decision 0014): the
    store tools live in ``dhc.tooling.artifact_tools`` with their own
    context.
    """

    agent_id: str
    runtime: Any = None
    bus: Any = None
    channels: dict[str, Any] = field(default_factory=dict)

    # -- convenience accessors ----------------------------------------------

    @property
    def messenger(self) -> Any:
        """The bound messenger facade (or ``None`` when not wired)."""
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


def _room(ctx: ToolContext, name: str) -> Room:
    """Join (creating if needed) the shared room *name*; return it."""
    if ctx.rooms is None:
        raise RuntimeError("no room manager wired into the tools layer")
    return ctx.rooms.join(ctx.agent_id, name)


def _post(ctx: ToolContext, room_name: str, body: str) -> Message:
    """Post *body* to *room_name* as the calling agent."""
    if ctx.rooms is None:
        raise RuntimeError("no room manager wired into the tools layer")
    return ctx.rooms.post(ctx.agent_id, room_name, body)


def _channel_read(ctx: ToolContext, topic: str) -> list[Message]:
    """Return the room's traffic in post order (empty for unknown rooms)."""
    if ctx.rooms is None:
        raise RuntimeError("no room manager wired into the tools layer")
    return ctx.rooms.messages(topic)


def _escalate(ctx: ToolContext, requirement: str, reason: str) -> Event:
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


def _ask_operator(ctx: ToolContext, question: str) -> Event:
    """Ask the operator *question* as the calling agent."""
    if ctx.questions is None:
        raise RuntimeError("no operator-question channel wired into the tools layer")
    return ctx.questions.ask(ctx.agent_id, question)


def _list_tools(ctx: ToolContext) -> list[str]:
    """Return the names of the installed tools.

    Reads the runtime's accumulated ``_installed_tool_names`` — the union of
    the names every registration function (this one and
    ``dhc.tooling.register_artifact_tools``) has contributed — so a runtime
    without the store tooling does not advertise ``publish``.
    """
    names = getattr(ctx.runtime, "_installed_tool_names", None)
    if names is None:
        names = _TOOL_NAMES
    return sorted(names)


def _events(ctx: ToolContext) -> list:
    """The agent's own settled events, consume-once (G-04).

    Wraps the runtime's ``tool_events`` surface: the agent reads its own
    settled events on its own schedule (its choice, per INFO-053) without
    rewriting the runner. The consume-once cursor is the tool's own, so the
    agent's consumption never steals from the default runner's ``observe``
    (``_event_cursors``) or the caps watchdog (``_caps_cursors``). The
    discipline guarantees (FIFO, at-most-once, persist-before-execute)
    remain runtime-owned — this only advances a read cursor over the
    already-persisted, ordered stream.
    """
    if ctx.runtime is None:
        raise RuntimeError("no runtime wired into the tools layer")
    return ctx.runtime.tool_events(ctx.agent_id)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

#: The canonical tool names installed by :func:`register_default_tools`.
#: (The four artifact store tools are a separate set, installed by
#: ``dhc.tooling.register_artifact_tools``; ``list_tools`` reports the
#: union of whatever is actually installed on the runtime.)
_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "room",
        "messenger",
        "escalate",
        "ask_operator",
        "post",
        "channel_read",
        "list_tools",
        "events",
    }
)


def _bind(ctx: ToolContext) -> dict[str, Callable[..., Any]]:
    """Build the namespace callables bound to *ctx* (one per tool name).

    ``messenger`` is an object (a per-agent facade with methods), not a
    callable — it is installed as a namespace value like the reference's
    tool objects.
    """
    return {
        "room": lambda name: _room(ctx, name),
        "messenger": ctx.messenger,
        "escalate": lambda requirement, reason: _escalate(
            ctx, requirement, reason
        ),
        "ask_operator": lambda question: _ask_operator(ctx, question),
        "post": lambda room_name, body: _post(ctx, room_name, body),
        "channel_read": lambda topic: _channel_read(ctx, topic),
        "list_tools": lambda: _list_tools(ctx),
        "events": lambda: _events(ctx),
    }


def register_default_tools(
    runtime: Any,
    bus: Any = None,
    channels: Optional[dict[str, Any]] = None,
) -> None:
    """Install the default tools as namespace callables on *runtime*.

    The runtime's namespace builder (``_build_namespace``) is wrapped so each
    agent's turn namespace gains the tools bound to that agent's
    :class:`ToolContext`. The core runtime itself is untouched: it keeps its
    slim base namespace; the tools are composed in here.

    The artifact store tools are NOT installed here (decision 0014) — they
    come from ``dhc.tooling.register_artifact_tools``.

    *bus* is duck-typed (``publish(event)``); *channels* maps names to
    channel facades (``messenger``, ``rooms``, ``escalations``, ``questions``).
    A channel value may be a plain object or a callable ``(agent_id) -> bound
    facade`` — the callable form is used for per-agent facades (e.g. the
    messenger bound to the calling agent).
    """
    channels = dict(channels or {})
    original = getattr(runtime, "_build_namespace", None)
    names = set(getattr(runtime, "_installed_tool_names", ()))
    names.update(_TOOL_NAMES)
    runtime._installed_tool_names = names

    def build(agent: Any) -> dict:
        ns = original(agent) if original is not None else {}
        resolved: dict[str, Any] = {}
        for name, channel in channels.items():
            resolved[name] = channel(agent.id) if callable(channel) else channel
        ctx = ToolContext(
            agent_id=agent.id,
            runtime=runtime,
            bus=bus,
            channels=resolved,
        )
        ns.update(_bind(ctx))
        return ns

    runtime._build_namespace = build  # type: ignore[method-assign]