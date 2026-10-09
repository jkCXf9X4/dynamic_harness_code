"""The ceiling-caps watchdog (D2): a pure monitor/predicate.

Moved verbatim from ``runtime.py`` (the loop concern): the per-step ceiling
caps check the pump runs between steps. The thresholds live in the
runtime's settings/state (which STAYS in ``runtime.py``); this module only
decides, given the resolved config and the live facts, which cap — if any —
is exceeded. All runtime-state access (the lock-guarded child count, the
event-bus drain) is supplied by the caller as lazy thunks so this predicate
stays pure and side-effect-free.

Cap names (the crash-event payload keys): ``wall_clock``, ``iterations``,
``children``, ``workspace_bytes``, ``messages_per_step``.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Optional

#: Caps watchdog defaults (overridable via settings; Step 5 owns full config:
#: SafetyConfig.max_workspace_bytes / max_children / max_messages_per_step).
_DEFAULT_TIMEOUT_SECONDS = 7200.0
_DEFAULT_MAX_ITERATIONS = 400
_DEFAULT_MAX_CHILDREN = 32
_DEFAULT_MAX_WORKSPACE_BYTES = 1 << 20  # 1 MiB
#: Message-rate cap is disabled by default; enforced only when settings
#: provide ``max_messages_per_step`` (Step 5 owns full config).
_DEFAULT_MAX_MESSAGES_PER_STEP = None


def read_cap(settings: Any, name: str, default: Any) -> Any:
    """Read a cap from *settings* None-safely (safety config first).

    Moved from ``Runtime._cap``: safety.<name> wins, then the top-level
    settings attribute, then *default*.
    """
    s = settings
    if s is None:
        return default
    safety = getattr(getattr(s, "config", None), "safety", None)
    if safety is not None:
        value = getattr(safety, name, None)
        if value is not None:
            return value
    return getattr(s, name, default)


def cap_limit(cap: str, settings: Any) -> Any:
    """The configured limit for a cap name (for the crash event payload)."""
    return {
        "wall_clock": read_cap(settings, "timeout_seconds", _DEFAULT_TIMEOUT_SECONDS),
        "iterations": read_cap(settings, "max_iterations", _DEFAULT_MAX_ITERATIONS),
        "children": read_cap(settings, "max_children", None)
        or read_cap(settings, "max_agents", _DEFAULT_MAX_CHILDREN),
        "workspace_bytes": read_cap(settings, "max_workspace_bytes", _DEFAULT_MAX_WORKSPACE_BYTES),
        "messages_per_step": read_cap(settings, "max_messages_per_step", _DEFAULT_MAX_MESSAGES_PER_STEP),
    }.get(cap)


def caps_exceeded(
    agent_id: str,
    engine: Any,
    step_count: int,
    started_ts: float,
    *,
    settings: Any,
    child_count: Callable[[], int],
    pending_messages: Callable[[], int],
    parked_seconds: float = 0.0,
) -> Optional[str]:
    """Return the name of the first ceiling cap exceeded, else None.

    Moved from ``Runtime._caps_watchdog``. Reads caps from *settings*
    None-safely (safety.timeout_seconds / max_iterations / max_agents /
    max_workspace_bytes / max_children / max_messages_per_step; Step 5 owns
    full config). Tests force caps via a tiny settings object.

    *child_count* and *pending_messages* are lazy thunks supplied by the
    caller (the runtime wrapper): they touch runtime state (the registry
    lock, the event-bus drain) and are invoked only when the corresponding
    cap is enabled — the drain must NOT run when the message-rate cap is
    disabled, or pending events would be consumed.
    """
    # Wall clock (safety.timeout_seconds). Parked time is credited
    # (decision 0008): time spent parked on `yield Await(child)` /
    # `yield Sleep(t)` does not count against the ceiling — waiting on
    # others consumes no agent budget (INFO-053). The credit is supplied by
    # the pump (cumulative parked seconds); it never exceeds elapsed time.
    timeout_seconds = read_cap(settings, "timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)
    if timeout_seconds is not None and (
        time.time() - started_ts - max(parked_seconds, 0.0) > timeout_seconds
    ):
        return "wall_clock"
    # Step count (safety.max_iterations).
    max_iterations = read_cap(settings, "max_iterations", _DEFAULT_MAX_ITERATIONS)
    if max_iterations is not None and step_count >= max_iterations:
        return "iterations"
    # Child count (safety.max_children, falling back to safety.max_agents).
    max_children = read_cap(settings, "max_children", None)
    if max_children is None:
        max_children = read_cap(settings, "max_agents", _DEFAULT_MAX_CHILDREN)
    if max_children is not None:
        if child_count() >= max_children:
            return "children"
    # Workspace bytes (module constant unless settings provide one).
    max_workspace_bytes = read_cap(settings, "max_workspace_bytes", _DEFAULT_MAX_WORKSPACE_BYTES)
    if max_workspace_bytes is not None:
        try:
            ws = engine.globals_for(agent_id)
            size = sum(len(str(v)) for v in ws.values())
        except Exception:  # noqa: BLE001 - sizing is best-effort
            size = 0
        if size > max_workspace_bytes:
            return "workspace_bytes"
    # Message rate (module constant unless settings provide one).
    max_messages = read_cap(settings, "max_messages_per_step", _DEFAULT_MAX_MESSAGES_PER_STEP)
    if max_messages is not None:
        if pending_messages() > max_messages:
            return "messages_per_step"
    return None
