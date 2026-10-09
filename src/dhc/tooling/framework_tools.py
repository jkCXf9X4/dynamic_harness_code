"""The framework-surface tools: list_tools + events as REPL namespace tools.

Decision 0016: this module lives in ``dhc.tooling`` — the agent's composed
world, everything installed into agent REPL namespaces beyond the core
actions — because it installs REPL tools, even though the tools themselves
wrap FRAMEWORK surfaces: ``list_tools`` (introspection of the installed
tools) and ``events`` (the agent's own consume-once event read over
``Runtime.tool_events``). The core namespace actions (``spawn``,
``complete``, ``send``, ...) come from ``dhc.framework`` itself; the
channel tools (``room``, ``messenger``, ``escalate``, ``ask_operator``,
``post``, ``channel_read``) live in :mod:`dhc.tooling.channel_tools`
(channels are tooling composed over the core send primitive, decision
0015), and the artifact store tools (``publish``, ``read_artifact``,
``archive``, ``list_artifacts``) live in
:mod:`dhc.tooling.artifact_tools` (decision 0014).

Tools receive a lightweight :class:`ToolContext` (agent_id + duck-typed
collaborators), never the :class:`~dhc.framework.agent.Agent` itself —
mirroring the reference project's ``core/tools/`` separation. The runtime
stays slim: its base namespace contains only core names; everything else
is composed in by ``dhc/wiring.py`` via the registration functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


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

    The artifact store and the communication channels deliberately have no
    slot here (decisions 0014/0015): their tools live in ``dhc.tooling``
    with their own contexts.
    """

    agent_id: str
    runtime: Any = None
    bus: Any = None


# --------------------------------------------------------------------------- #
# Tool implementations (all take/return simple values)
# --------------------------------------------------------------------------- #


def _list_tools(ctx: ToolContext) -> list[str]:
    """Return the names of the installed tools.

    Reads the runtime's accumulated ``_installed_tool_names`` — the union of
    the names every registration function (this one,
    ``dhc.tooling.register_artifact_tools``, and
    ``dhc.tooling.register_channel_tools``) has contributed — so a runtime
    without the store or channel tooling does not advertise their tools.
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
#: (The four artifact store tools come from
#: ``dhc.tooling.register_artifact_tools``; the six channel tools from
#: ``dhc.tooling.register_channel_tools``; ``list_tools`` reports the union
#: of whatever is actually installed on the runtime.)
_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "list_tools",
        "events",
    }
)


def _bind(ctx: ToolContext) -> dict[str, Callable[..., Any]]:
    """Build the namespace callables bound to *ctx* (one per tool name)."""
    return {
        "list_tools": lambda: _list_tools(ctx),
        "events": lambda: _events(ctx),
    }


def register_default_tools(
    runtime: Any,
    bus: Any = None,
) -> None:
    """Install the framework tools as namespace callables on *runtime*.

    The runtime's namespace builder (``_build_namespace``) is wrapped so each
    agent's turn namespace gains the tools bound to that agent's
    :class:`ToolContext`. The core runtime itself is untouched: it keeps its
    slim base namespace (which now includes the directed-message primitive
    ``send``, decision 0015); the tools are composed in here.

    The artifact store tools and the channel tools are NOT installed here
    (decisions 0014/0015) — they come from ``dhc.tooling``.

    *bus* is duck-typed (``publish(event)``).
    """
    original = getattr(runtime, "_build_namespace", None)
    names = set(getattr(runtime, "_installed_tool_names", ()))
    names.update(_TOOL_NAMES)
    runtime._installed_tool_names = names

    def build(agent: Any) -> dict:
        ns = original(agent) if original is not None else {}
        ctx = ToolContext(
            agent_id=agent.id,
            runtime=runtime,
            bus=bus,
        )
        ns.update(_bind(ctx))
        return ns

    runtime._build_namespace = build  # type: ignore[method-assign]
