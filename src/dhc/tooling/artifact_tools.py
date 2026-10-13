"""Artifact store tools: publish/read/archive/list as REPL namespace tools.

Operator tooling (decision 0014): these namespace callables are the
agent-facing bridge to the operator's artifact store. They persist findings
as content-addressed artifacts and emit the framework's
``artifact_published`` event on the bus — the framework core never sees the
store, only the event.

Installed by :func:`register_artifact_tools` with the same namespace-wrapping
mechanics as ``dhc.tooling.framework_tools.register_default_tools``; the composition root
(``wiring.build_runtime``) is the caller. The four tools are the ONLY
namespace names this module contributes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from ..data.models import Artifact, Event, EventKind
from ..errors import ArtifactNotFoundError, ChannelError


# --------------------------------------------------------------------------- #
# Context
# --------------------------------------------------------------------------- #


@dataclass
class ArtifactToolContext:
    """The lightweight surface the artifact tools receive — never the Agent.

    * ``store`` — anything with ``put(artifact)`` or the adapter-style
      ``publish(headline, summary, report)`` contract, plus ``get``,
      ``get_headline``/``get_summary``/``get_report``, ``list_ids()``, and
      ``exists(artifact_id)``.
    * ``bus`` — anything with ``publish(event)`` (the event bus); ``None``
      means publish without emitting the ``artifact_published`` event.
    """

    agent_id: str
    store: Any
    bus: Any = None


# --------------------------------------------------------------------------- #
# Tool implementations (all take/return simple values)
# --------------------------------------------------------------------------- #


def _publish(ctx: ArtifactToolContext, headline: str, summary: str, report: Any) -> Artifact:
    """Persist a finding and emit the ``artifact_published`` boundary event.

    Wraps ``store.put`` (the raw :class:`~dhc.tooling.ArtifactStore`
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
    ctx: ArtifactToolContext, artifact_id: str, level: str = "summary"
) -> str:
    """Progressive disclosure: headline -> summary -> report tiers.

    Accepted levels: ``headline``, ``summary``, ``report`` (the full body),
    plus ``full`` and ``raw`` as aliases of ``report``.
    """
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
        return json.dumps(report, ensure_ascii=False, sort_keys=True, default=str)
    raise ValueError(
        f"unknown disclosure level {level!r}; expected "
        "headline|summary|report|full|raw"
    )


def _archive(ctx: ArtifactToolContext, artifact_id: str) -> str:
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
    raise ArtifactNotFoundError(
        f"no on-disk path derivable for artifact {artifact_id!r} "
        "(store exposes neither path_for nor a root)"
    )


def _list_artifacts(ctx: ArtifactToolContext) -> list[str]:
    """Return all stored artifact ids (stable order)."""
    if ctx.store is None:
        raise RuntimeError("no artifact store wired into the tools layer")
    return list(ctx.store.list_ids())


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #

#: The canonical tool names installed by :func:`register_artifact_tools`.
_ARTIFACT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "publish",
        "read_artifact",
        "archive",
        "list_artifacts",
    }
)


def _bind(ctx: ArtifactToolContext) -> dict[str, Callable[..., Any]]:
    """Build the store namespace callables bound to *ctx* (one per tool)."""
    return {
        "publish": lambda headline, summary, report: _publish(
            ctx, headline, summary, report
        ),
        "read_artifact": lambda artifact_id, level="summary": _read_artifact(
            ctx, artifact_id, level
        ),
        "archive": lambda artifact_id: _archive(ctx, artifact_id),
        "list_artifacts": lambda: _list_artifacts(ctx),
    }


def _register_surface_entries() -> None:
    """Register the artifact-tool surface entries (idempotent, W1.2).

    ``read_artifact`` is tier CORE — the flagship read half the historical
    prompt omitted (F1).
    """
    from ..framework.surface import SurfaceEntry, default_registry

    default_registry.register(
        SurfaceEntry(
            name="publish",
            fn=_publish,
            doc="Persist a finding as a durable artifact.",
            tier="core",
            call="publish(headline, summary, report)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="read_artifact",
            fn=_read_artifact,
            doc=(
                "Read an artifact (progressive disclosure: headline/summary/"
                "report; full and raw are aliases of report)."
            ),
            tier="core",
            call="read_artifact(artifact_id, level='summary')",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="archive",
            fn=_archive,
            doc="Copy an artifact into the durable archive.",
            tier="core",
            call="archive(artifact_id)",
        )
    )
    default_registry.register(
        SurfaceEntry(
            name="list_artifacts",
            fn=_list_artifacts,
            doc="List the stored artifact ids.",
            tier="core",
            call="list_artifacts()",
        )
    )


def register_artifact_tools(
    runtime: Any,
    store: Any,
    bus: Any = None,
) -> None:
    """Install the artifact store tools as namespace callables on *runtime*.

    Same mechanics as ``dhc.tooling.framework_tools.register_default_tools``: W1.3
    appends a builder to the runtime's ordered, public namespace-builder
    chain (``runtime.register_namespace_builder``) so each agent's turn
    namespace gains the store tools bound to that agent. The framework
    core is untouched: it keeps its slim base namespace; the store tools
    are composed in here.

    *store* is duck-typed (raw ``put(artifact)`` or adapter-style
    ``publish(h, s, r)`` plus the read tiers); *bus* is duck-typed
    (``publish(event)``) and is where the ``artifact_published`` event is
    emitted after each persist.
    """
    names = set(getattr(runtime, "_installed_tool_names", ()))
    names.update(_ARTIFACT_TOOL_NAMES)
    runtime._installed_tool_names = names

    _register_surface_entries()

    def build(agent: Any) -> dict:
        ctx = ArtifactToolContext(agent_id=agent.id, store=store, bus=bus)
        return _bind(ctx)

    runtime.register_namespace_builder(build, name="artifact_tools")


__all__ = [
    "ArtifactToolContext",
    "register_artifact_tools",
]

# The artifact-tool surface entries are registered at import time (W1.2):
# the registry must be complete before any runtime is wired.
_register_surface_entries()
