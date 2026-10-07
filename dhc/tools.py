"""The tools layer: artifact store and communication channels as REPL tools.

The architectural goal (refactor scoping brief §c6/§c8): the CORE is only
``dhc/runtime.py`` + ``dhc/event_stream.py``. The artifact store and the
communication channels are *not* core collaborators — they are REPL-executed
Python tools: namespace callables developed separately from the core and
installed by :func:`register_default_tools`.

Tools receive a lightweight :class:`ToolContext` (agent_id + duck-typed
collaborators), never the :class:`~dhc.agent.Agent` itself — mirroring the
reference project's ``core/tools/`` separation. The runtime stays slim: its
base namespace contains only core names; everything else is composed in by
``dhc/wiring.py`` via this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .errors import ChannelError
from .models import Artifact, Event, EventKind, Message, Room


# --------------------------------------------------------------------------- #
# ToolContext
# --------------------------------------------------------------------------- #


@dataclass
class ToolContext:
    """The lightweight surface a tool receives — never the Agent.

    All collaborators are duck-typed so the tools layer works standalone
    (tests, REPL sessions) as well as fully wired:

    * ``runtime`` — anything exposing the supervision surface the tool needs
      (e.g. ``children_of``, ``get``); may be ``None`` for store-only tools.
    * ``store`` — anything with ``publish(headline, summary, report)``,
      ``get(artifact_id)``, ``get_headline``/``get_summary``/``get_report``,
      ``list_ids()``, and ``exists(artifact_id)``.
    * ``bus`` — anything with ``publish(event)`` (the event bus).
    * ``channels`` — a dict of named channel facades: ``messenger``,
      ``rooms``, ``escalations``, ``questions``.
    """

    agent_id: str
    runtime: Any = None
    store: Any = None
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


def _publish(ctx: ToolContext, headline: str, summary: str, report: Any) -> Artifact:
    """Persist a finding and emit the ``artifact_published`` boundary event.

    Wraps ``store.put`` (the raw :class:`~dhc.artifact_store.ArtifactStore`
    contract); also accepts the adapter-style ``store.publish(h, s, r)``
    contract for duck-typed stores.
    """
    if ctx.store is None:
        raise RuntimeError("no artifact store wired into the tools layer")
    if hasattr(ctx.store, "put"):
        artifact = Artifact(headline=headline, summary=summary, report=report)
        ctx.store.put(artifact)
    else:
        artifact = ctx.store.publish(headline, summary, report)
    if ctx.bus is not None:
        ctx.bus.publish(
            Event(
                kind=EventKind.artifact_published,
                agent_id=ctx.agent_id,
                payload={"artifact_id": artifact.id},
            )
        )
    return artifact


def _read_artifact(
    ctx: ToolContext, artifact_id: str, level: str = "summary"
) -> str:
    """Progressive disclosure: headline -> summary -> report tiers."""
    if ctx.store is None:
        raise RuntimeError("no artifact store wired into the tools layer")
    if level == "headline":
        return ctx.store.get_headline(artifact_id)
    if level == "summary":
        return ctx.store.get_summary(artifact_id)
    if level in ("report", "full", "raw"):
        report = ctx.store.get_report(artifact_id)
        if isinstance(report, str):
            return report
        import json

        return json.dumps(report, ensure_ascii=False, sort_keys=True, default=str)
    raise ValueError(
        f"unknown disclosure level {level!r}; expected headline|summary|report"
    )


def _archive(ctx: ToolContext, artifact_id: str) -> str:
    """Return the on-disk path of the stored artifact's report body."""
    if ctx.store is None:
        raise RuntimeError("no artifact store wired into the tools layer")
    if not ctx.store.exists(artifact_id):
        raise ChannelError(f"no artifact with id {artifact_id!r}")
    path = getattr(ctx.store, "path_for", None)
    if callable(path):
        return str(path(artifact_id))
    # Duck-typed fallback: the raw ArtifactStore exposes its root and the
    # report layout (root/artifacts/<id>.json).
    root = getattr(ctx.store, "_root", None) or getattr(ctx.store, "root", None)
    if root is not None:
        return str(Path(root) / "artifacts" / f"{artifact_id}.json")
    return artifact_id


def _list_artifacts(ctx: ToolContext) -> list[str]:
    """Return all stored artifact ids (stable order)."""
    if ctx.store is None:
        raise RuntimeError("no artifact store wired into the tools layer")
    return list(ctx.store.list_ids())


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
    """Return the names of the installed tools."""
    return sorted(_TOOL_NAMES)


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

#: The canonical tool names installed by :func:`register_default_tools`.
_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "publish",
        "read_artifact",
        "archive",
        "list_artifacts",
        "room",
        "messenger",
        "escalate",
        "ask_operator",
        "post",
        "channel_read",
        "list_tools",
    }
)


def _bind(ctx: ToolContext) -> dict[str, Callable[..., Any]]:
    """Build the namespace callables bound to *ctx* (one per tool name).

    ``messenger`` is an object (a per-agent facade with methods), not a
    callable — it is installed as a namespace value like the reference's
    tool objects.
    """
    return {
        "publish": lambda headline, summary, report: _publish(
            ctx, headline, summary, report
        ),
        "read_artifact": lambda artifact_id, level="summary": _read_artifact(
            ctx, artifact_id, level
        ),
        "archive": lambda artifact_id: _archive(ctx, artifact_id),
        "list_artifacts": lambda: _list_artifacts(ctx),
        "room": lambda name: _room(ctx, name),
        "messenger": ctx.messenger,
        "escalate": lambda requirement, reason: _escalate(
            ctx, requirement, reason
        ),
        "ask_operator": lambda question: _ask_operator(ctx, question),
        "post": lambda room_name, body: _post(ctx, room_name, body),
        "channel_read": lambda topic: _channel_read(ctx, topic),
        "list_tools": lambda: _list_tools(ctx),
    }


def register_default_tools(
    runtime: Any,
    store: Any = None,
    bus: Any = None,
    channels: Optional[dict[str, Any]] = None,
) -> None:
    """Install the default tools as namespace callables on *runtime*.

    The runtime's namespace builder (``_build_namespace``) is wrapped so each
    agent's turn namespace gains the tools bound to that agent's
    :class:`ToolContext`. The core runtime itself is untouched: it keeps its
    slim base namespace; the tools are composed in here.

    *store* is duck-typed (``publish``/``get``/``get_headline``/...);
    *bus* is duck-typed (``publish(event)``); *channels* maps names to
    channel facades (``messenger``, ``rooms``, ``escalations``, ``questions``).
    A channel value may be a plain object or a callable ``(agent_id) -> bound
    facade`` — the callable form is used for per-agent facades (e.g. the
    messenger bound to the calling agent).
    """
    channels = dict(channels or {})
    original = getattr(runtime, "_build_namespace", None)

    def build(agent: Any) -> dict:
        ns = original(agent) if original is not None else {}
        resolved: dict[str, Any] = {}
        for name, channel in channels.items():
            resolved[name] = channel(agent.id) if callable(channel) else channel
        ctx = ToolContext(
            agent_id=agent.id,
            runtime=runtime,
            store=store,
            bus=bus,
            channels=resolved,
        )
        ns.update(_bind(ctx))
        return ns

    runtime._build_namespace = build  # type: ignore[method-assign]