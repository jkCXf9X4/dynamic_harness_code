"""The agent surface registry: the single source of truth (W1, F2).

Every name an action block can call exists exactly once here — as a
:class:`SurfaceEntry` with its tier — and everything that *describes* the
API is generated from this registry:

* the prompt's API section (:meth:`SurfaceRegistry.prompt_section` —
  consumed by :func:`dhc.llm.driver.default_build_prompt`),
* ``list_tools()`` (:meth:`SurfaceRegistry.list_tools` — the core+advanced
  listing the agent can introspect),
* the prompt↔API conformance test (``tests/llm/test_prompt_conformance.py``),
  which guards the registry against drift in both directions.

Tiers (decision D2):

* ``core`` — goes into the prompt's API section (the ~23 names an LLM
  needs) and into ``list_tools()``.
* ``advanced`` — visible via ``list_tools()`` but not prompt-visible
  (reachable, not advertised).
* ``internal`` — never advertised; injected machinery (the fabrication
  kit, the driver factory) that stays callable but undocumented.

The registry is a process-wide singleton (:data:`default_registry`): the
agent surface is a property of the wired stack, not of one Runtime
instance, and the prompt layer must be able to render it without holding
a runtime. Registration is idempotent — re-registering a name replaces
its entry — so the registration sites (Runtime core, the three tooling
registrations, the wiring root, the fabrication kit) can run any number
of times, in any test order, without accumulating state.

The registry is METADATA: it does not build namespaces. Namespaces are
composed by the ordered builders (``Runtime.register_namespace_builder``);
this module only describes what those builders install, so the
description and the injection can never silently diverge (the
conformance test cross-checks them).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional

#: The valid tiers (decision D2).
TIERS = ("core", "advanced", "internal")

#: The prompt sentence the generated API section is rendered into. The
#: conformance test parses this shape — keep it stable.
_PROMPT_PREFIX = "Available in the namespace: "


@dataclass(frozen=True)
class SurfaceEntry:
    """One name in the agent surface.

    * ``name`` — the injected namespace name (e.g. ``"read_artifact"``).
    * ``fn`` — a representative callable for the entry (used for
      introspection; ``None`` when the injected binding is per-agent —
      a closure or facade object — so no stable function exists).
    * ``doc`` — one line, written for an LLM reader.
    * ``tier`` — ``"core"`` (prompt + list_tools), ``"advanced"``
      (list_tools only) or ``"internal"`` (never advertised).
    * ``call`` — the prompt call form for core entries, e.g.
      ``"publish(headline, summary, report)"`` or
      ``"messenger.send(recipient_id, body)"``. Required for core
      (the prompt renders it verbatim and the conformance test
      arity-checks it); optional otherwise.
    """

    name: str
    fn: Optional[Callable[..., Any]]
    doc: str
    tier: str = "advanced"
    call: Optional[str] = None

    def __post_init__(self) -> None:
        if self.tier not in TIERS:
            raise ValueError(
                f"surface entry {self.name!r}: tier must be one of {TIERS}, "
                f"got {self.tier!r}"
            )
        if self.tier == "core":
            if not self.call:
                raise ValueError(
                    f"surface entry {self.name!r}: core entries need a "
                    "call form (the prompt renders it)"
                )
            base = self.call.split("(")[0]
            if base != self.name and not base.startswith(self.name + "."):
                raise ValueError(
                    f"surface entry {self.name!r}: call form {self.call!r} "
                    "must name this entry (or its attribute)"
                )


class SurfaceRegistry:
    """The ordered set of surface entries; the single source of truth."""

    def __init__(self) -> None:
        self._entries: dict[str, SurfaceEntry] = {}

    # -- mutation -----------------------------------------------------------

    def register(self, entry: SurfaceEntry) -> None:
        """Register (or replace) *entry* — idempotent by name."""
        self._entries[entry.name] = entry

    # -- views --------------------------------------------------------------

    def entries(self) -> Iterator[SurfaceEntry]:
        """Iterate all entries (registration order)."""
        return iter(self._entries.values())

    def get(self, name: str) -> Optional[SurfaceEntry]:
        return self._entries.get(name)

    def of_tier(self, *tiers: str) -> list[SurfaceEntry]:
        """Entries in the given tier(s), sorted by name (deterministic)."""
        wanted = set(tiers)
        return sorted(
            (e for e in self._entries.values() if e.tier in wanted),
            key=lambda e: e.name,
        )

    def namespace(self) -> dict[str, Callable[..., Any]]:
        """The name→callable view of the surface (entries with a stable fn).

        Metadata only — the injected namespace is composed by the
        runtime's registered builders; this view covers the entries that
        have a representative callable.
        """
        return {e.name: e.fn for e in self._entries.values() if e.fn is not None}

    def prompt_section(self) -> str:
        """The generated API section for the core tier (deterministic).

        One sentence listing every core call form, sorted by name — the
        generated replacement for the historical hand-written API literal
        the driver used to carry. The conformance test parses this shape.
        """
        calls = [e.call for e in self.of_tier("core")]
        if not calls:
            return _PROMPT_PREFIX.rstrip(": ")
        return _PROMPT_PREFIX + ", ".join(calls) + "."

    def list_tools(self) -> list[str]:
        """The core+advanced names — what ``list_tools()`` reports."""
        return [e.name for e in self.of_tier("core", "advanced")]

    def __len__(self) -> int:
        return len(self._entries)

    def __contains__(self, name: object) -> bool:
        return name in self._entries


#: The process-wide agent surface. The composition root (``dhc.wiring``),
#: the Runtime core, and the tooling registrations all register into this
#: one registry; the prompt layer renders from it.
default_registry = SurfaceRegistry()
