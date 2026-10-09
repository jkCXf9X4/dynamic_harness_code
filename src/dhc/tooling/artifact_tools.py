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
from ..errors import ChannelError


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
        return json.dumps(report, ensure_ascii=False, sort_keys=True, default=str)
    raise ValueError(
        f"unknown disclosure level {level!r}; expected headline|summary|report"
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
    return artifact_id


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


def register_artifact_tools(
    runtime: Any,
    store: Any,
    bus: Any = None,
) -> None:
    """Install the artifact store tools as namespace callables on *runtime*.

    Same mechanics as ``dhc.tooling.framework_tools.register_default_tools``: the
    runtime's namespace builder (``_build_namespace``) is wrapped so each
    agent's turn namespace gains the store tools bound to that agent. The
    framework core is untouched: it keeps its slim base namespace; the store
    tools are composed in here.

    *store* is duck-typed (raw ``put(artifact)`` or adapter-style
    ``publish(h, s, r)`` plus the read tiers); *bus* is duck-typed
    (``publish(event)``) and is where the ``artifact_published`` event is
    emitted after each persist.
    """
    original = getattr(runtime, "_build_namespace", None)
    names = set(getattr(runtime, "_installed_tool_names", ()))
    names.update(_ARTIFACT_TOOL_NAMES)
    runtime._installed_tool_names = names

    def build(agent: Any) -> dict:
        ns = original(agent) if original is not None else {}
        ctx = ArtifactToolContext(agent_id=agent.id, store=store, bus=bus)
        ns.update(_bind(ctx))
        return ns

    runtime._build_namespace = build  # type: ignore[method-assign]


__all__ = [
    "ArtifactToolContext",
    "register_artifact_tools",
]
