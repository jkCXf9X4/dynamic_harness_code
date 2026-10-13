"""The framework-surface tools: list_tools, events, ack, answers, gather.

Decision 0016: this module lives in ``dhc.tooling`` — the agent's composed
world, everything installed into agent REPL namespaces beyond the core
actions — because it installs REPL tools, even though the tools themselves
wrap FRAMEWORK surfaces: ``list_tools`` (introspection of the installed
tools), ``events`` (the agent's own consume-once event read over
``Runtime.tool_events``), and the Wave 3 consolidation (W3.5/W3.6/W3.8):
``ack`` (the parent side of the escalation loop), ``answers`` (the asker
side of the operator-question loop), and ``gather`` (the fan-out join
helper). The core namespace actions (``spawn``, ``complete``, ``send``,
...) come from ``dhc.framework`` itself; the channel tools (``room``,
``messenger``, ``escalate``, ``ask_operator``, ``post``,
``channel_read``) live in :mod:`dhc.tooling.channel_tools` (channels are
tooling composed over the core send primitive, decision 0015), and the
artifact store tools (``publish``, ``read_artifact``, ``archive``,
``list_artifacts``) live in :mod:`dhc.tooling.artifact_tools` (decision
0014).

Tools receive a lightweight :class:`ToolContext` (agent_id + duck-typed
collaborators), never the :class:`~dhc.framework.agent.Agent` itself —
mirroring the reference project's ``core/tools/`` separation. The runtime
stays slim: its base namespace contains only core names; everything else
is composed in by ``dhc/wiring.py`` via the registration functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..data.models import AgentStatus, Completion
from ..framework.pump import Await, Poll, Sleep


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

    Reads the surface registry (W1.6): the core+advanced tier IS the
    installed surface — the registry is the single source of truth the
    prompt's API section is also generated from, so ``list_tools()`` and
    the prompt can never disagree. Falls back to the runtime's
    accumulated ``_installed_tool_names`` when no registry entry exists
    (a runtime with tools registered outside the registry).
    """
    from ..framework.surface import default_registry

    listed = default_registry.list_tools()
    if listed:
        return listed
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


def _ack(ctx: ToolContext, escalation_id: str) -> None:
    """Acknowledge the parent's escalation *escalation_id* (W3.6).

    The escalation loop's parent side: a child's ``escalate(requirement,
    reason)`` event carries ``payload["event_id"]``; the parent reads it
    (its ``events`` tool) and calls ``ack(escalation_id)`` to close the
    loop. The channel raises ``ChannelError`` for an unknown or already
    acknowledged id — the caller sees the misuse, not a silent no-op.
    """
    escalations = getattr(ctx.runtime, "escalations", None)
    if escalations is None:
        raise RuntimeError("no escalation channel wired")
    escalations.ack(ctx.agent_id, escalation_id)


def _answers(ctx: ToolContext, question_id: str) -> list[str]:
    """The operator's answers to the agent's question *question_id* (W3.6).

    The question loop's asker side: ``ask_operator(question)`` returns the
    question event whose ``payload["event_id"]`` IS the question id; the
    asker polls ``answers(question_id)`` until the operator's answer text
    arrives (empty list while unanswered — polling, not blocking).
    """
    questions = getattr(ctx.runtime, "questions", None)
    if questions is None:
        raise RuntimeError("no operator-question channel wired")
    return [
        str(a.payload.get("answer", ""))
        for a in questions.answers_for(ctx.agent_id)
        if a.causal_id == question_id
    ]


def _gather(
    ctx: ToolContext, handles: list, *, return_failures: bool = False
) -> list[Completion]:
    """Join *handles* (spawned children) and aggregate their Completions (W3.8).

    The fan-out helper: spawn-all first (``spawn`` is non-blocking), then
    ``gather`` blocks on each handle in order (``runtime.await_``) and
    returns the settled :class:`~dhc.data.models.Completion` objects.

    * ``return_failures=False`` (default) — the simple success path: only
      the completed children are returned; failed/cancelled/timeout
      completions are dropped.
    * ``return_failures=True`` — every completion is returned so the caller
      can inspect ``c.status`` (``AgentStatus``) and handle failures
      selectively.

    ``gather`` itself never raises ``ChannelError`` — aggregation is
    ChannelError-free by construction. Handles may be ``AgentHandle``
    objects or bare agent id strings; an empty list returns ``[]``.
    """
    if ctx.runtime is None:
        raise RuntimeError("no runtime wired into the tools layer")
    completions: list[Completion] = []
    for handle in handles:
        agent_id = getattr(handle, "id", handle)
        completions.append(ctx.runtime.await_(agent_id))
    if return_failures:
        return completions
    return [c for c in completions if c.status == AgentStatus.completed]


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
        "ack",
        "answers",
        "gather",
    }
)


def _bind(ctx: ToolContext) -> dict[str, Callable[..., Any]]:
    """Build the namespace callables bound to *ctx* (one per tool name).

    The bound lambdas carry the arity the prompt teaches (the conformance
    test arity-checks the core call forms against these bound forms):
    ``ack(escalation_id)``, ``answers(question_id)``, and
    ``gather(handles, return_failures=False)``.
    """
    return {
        "list_tools": lambda: _list_tools(ctx),
        "events": lambda: _events(ctx),
        "ack": lambda escalation_id: _ack(ctx, escalation_id),
        "answers": lambda question_id: _answers(ctx, question_id),
        "gather": lambda handles, return_failures=False: _gather(
            ctx, handles, return_failures=return_failures
        ),
    }


def _register_surface_entries() -> None:
    """Register the framework-tool surface entries (idempotent, W1.2)."""
    from ..framework.surface import SurfaceEntry, default_registry

    default_registry.register(
        SurfaceEntry(
            name="list_tools",
            fn=_list_tools,
            doc="List the installed tool names (core + advanced surface).",
            tier="core",
            call="list_tools()",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="events",
            fn=_events,
            doc="The agent's own settled events, consume-once.",
            tier="advanced",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="ack",
            fn=_ack,
            doc="Acknowledge a child's escalation (closes the escalation loop).",
            tier="core",
            call="ack(escalation_id)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="answers",
            fn=_answers,
            doc="Poll the operator's answers to your question (empty until answered).",
            tier="core",
            call="answers(question_id)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="gather",
            fn=_gather,
            doc="Join spawned children and aggregate their Completions.",
            tier="core",
            call="gather(handles, return_failures=False)",
        )
    )


def _apply_wave3_tiers() -> None:
    """Re-assert the Wave 3 tier moves (W3.5 + W3.8) — idempotent.

    Registration is idempotent (re-registering replaces), so this module
    re-asserts the entries other registration sites own:

    * W3.8 — the pump's yield vocabulary (``Await`` / ``Poll`` / ``Sleep``,
      registered by the Runtime core as ``advanced`` with no call form)
      moves to ``core`` WITH call forms: the two documented await idioms
      (``Await(handle)`` — park until settled; ``Poll(handle)`` — check
      and resume) plus ``Sleep(seconds)``. The prompt's API section picks
      them up automatically — the registry is the single source of truth.
    * W3.5 — ``messenger`` (registered by the channel tools as ``core``
      with ``messenger.send(...)``) is demoted to ``advanced``: the prompt
      teaches the one send verb (``send``) only. The facade stays
      injected and callable — only its tier (and thus its prompt
      visibility) changes.
    """
    from ..framework.surface import SurfaceEntry, default_registry

    default_registry.register(
        SurfaceEntry(
            name="Await",
            fn=Await,
            doc="Yield: park the runner until the child settles (await idiom 1).",
            tier="core",
            call="Await(handle)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="Poll",
            fn=Poll,
            doc="Yield: check the child's status, then resume (await idiom 2).",
            tier="core",
            call="Poll(handle)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="Sleep",
            fn=Sleep,
            doc="Yield: pause the runner for a beat (stop-flag aware).",
            tier="core",
            call="Sleep(seconds)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="messenger",
            fn=None,
            doc="Per-agent facade: send + inbox/read-state sugar (advanced; prefer send).",
            tier="advanced",
        )
    )


def register_default_tools(
    runtime: Any,
    bus: Any = None,
) -> None:
    """Install the framework tools as namespace callables on *runtime*.

    W1.3: the tools are installed by appending a builder to the runtime's
    ordered, public namespace-builder chain
    (``runtime.register_namespace_builder``) — the historical private
    ``_build_namespace`` reassignment is gone. Each agent's turn namespace
    gains the tools bound to that agent's :class:`ToolContext`. The core
    runtime itself is untouched: it keeps its slim base namespace (which
    includes the directed-message primitive ``send``, decision 0015); the
    tools are composed in here.

    The artifact store tools and the channel tools are NOT installed here
    (decisions 0014/0015) — they come from ``dhc.tooling``.

    *bus* is duck-typed (``publish(event)``).
    """
    names = set(getattr(runtime, "_installed_tool_names", ()))
    names.update(_TOOL_NAMES)
    runtime._installed_tool_names = names

    _register_surface_entries()
    _apply_wave3_tiers()

    def build(agent: Any) -> dict:
        # Re-assert the Wave 3 tier moves (W3.5/W3.8) on every namespace
        # build: ``register_channel_tools`` re-registers its entries (e.g.
        # ``messenger`` as core) at call time, which would overwrite the
        # import-time demotion.  Re-asserting here (idempotent, cheap)
        # guarantees the tier moves are the last writer.
        _apply_wave3_tiers()
        ctx = ToolContext(
            agent_id=agent.id,
            runtime=runtime,
            bus=bus,
        )
        return _bind(ctx)

    runtime.register_namespace_builder(build, name="framework_tools")

# The framework-tool surface entries are registered at import time (W1.2):
# the registry must be complete before any runtime is wired — the prompt
# layer renders from it without holding a runtime instance. The Wave 3
# tier moves (W3.5/W3.8) are re-asserted right after: idempotent
# registration means the last writer wins, and this module is imported by
# the composition root (wiring) before any prompt is rendered.
_register_surface_entries()
_apply_wave3_tiers()
