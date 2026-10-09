"""Context triggers (INFO-021): the digest observe/trim seam.

The event-stream digest is the ONLY real pruning in the system: after every
``run_block`` the default loop's ``observe`` step appends the agent's fresh
events to the workspace digest and keeps only the last
:data:`DIGEST_KEEP` entries. This module makes that trigger explicit and
testable; :mod:`dhc.tooling.fabrication`'s ``make_observe`` is a thin delegate
with identical semantics.

The companion :class:`~dhc.llm.llm.ContextRotDetector` is observe-only: it
collects and logs rot signals on generated blocks but never prunes anything.
"""

from __future__ import annotations

from typing import Any, Callable, List

#: How many digest entries survive each observe step (the trim-50 contract).
DIGEST_KEEP = 50


def trim_digest(digest: List[Any], keep: int = DIGEST_KEEP) -> List[Any]:
    """Keep only the last *keep* entries of *digest*, in place.

    Identical semantics to the historical ``del digest[:-50]``: when the
    digest is shorter than *keep* it is left untouched.

    *keep* is sanitized: ``None`` and negative values are treated as 0
    (drop everything). Note that ``keep=0`` must NOT be implemented as
    ``del digest[:-0]`` — ``[:-0]`` is the empty slice ``[:0]``, a no-op.
    """
    if keep is None or keep < 0:
        keep = 0
    if keep:
        del digest[:-keep]
    else:
        del digest[:]
    return digest


def observe_digest(
    state: dict, events: List[Any], keep: int = DIGEST_KEEP
) -> List[Any]:
    """Append *events* to ``state["digests"]["events"]`` and trim to *keep*.

    Returns *events* (the fresh happenings), mirroring the default loop's
    observe step: the caller gets what was consumed, the workspace digest
    keeps the bounded recent history.
    """
    digest = state.setdefault("digests", {}).setdefault("events", [])
    digest.extend(events)
    trim_digest(digest, keep)
    return events


def make_observe(
    drain_completions: Callable[[], Any],
    fetch_events: Callable[[], List[Any]],
    state: dict,
) -> Callable[[], List[Any]]:
    """Build the default loop's observe hook over the context seam.

    Thin delegate: drains completion callbacks, fetches the fresh events,
    and hands them to :func:`observe_digest` for the extend + trim-50.
    """
    def observe() -> List[Any]:
        drain_completions()
        events = fetch_events()
        return observe_digest(state, events)

    return observe
