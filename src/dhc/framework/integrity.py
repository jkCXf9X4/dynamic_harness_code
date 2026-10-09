"""Fabrication integrity (IMP-001 Step 5, D4): ensure/re-seed between steps.

Moved verbatim from the pump loop in ``runtime.py`` (the loop concern): the
best-effort calls to the fabrication kit's ``ensure_fabrication`` re-seeder.
A broken/deleted fabrication (e.g. ``__runner = 42``) is re-seeded — before
the runner is advanced — so the agent continues instead of failing. The
re-seed itself lives in the kit (``dhc.llm.fabrication``); this module only
wraps the call sites' best-effort error handling.
"""

from __future__ import annotations

from typing import Any


def ensure_fabrication(kit: dict) -> None:
    """Best-effort: re-seed broken fabrications before the runner advances.

    The re-seed emits a crash event with the reseeded names (kit-owned
    behavior); failures here are swallowed — re-seeding is best-effort.
    """
    try:
        kit["ensure_fabrication"]()
    except Exception:  # noqa: BLE001 - re-seed is best-effort
        pass


def reseed_fabrication(kit: dict) -> Any:
    """Best-effort re-seed; returns the re-seeded names ([] on failure).

    Used on the suspended/abandoned path: a non-empty result means the pump
    may continue (the fabrication was repaired); an empty one means the
    runner is genuinely unavailable.
    """
    try:
        return kit["ensure_fabrication"]()
    except Exception:  # noqa: BLE001 - re-seed is best-effort
        return []
