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


# --------------------------------------------------------------------------- #
# Agent-set working budgets (G-01): min(agent_budget, ceiling)
# --------------------------------------------------------------------------- #
#
# The agent's working budgets live in its own workspace as ordinary data
# (``context.budgets``) — it may set, edit or delete them mid-run. The
# CEILING always comes from runtime settings; an agent budget can only
# TIGHTEN a limit (min-clamped here, in runtime code), never loosen one
# (guarantee R3: the agent never supplies the ceiling itself). Sanitization
# is defensive: wrong type / None / NaN / <= 0 -> treated as unset.

#: Agent-set budget keys -> the cap each can tighten. Both the
#: settings-style names (``max_iterations`` ...) and the cap-name aliases
#: (the crash-event payload keys) are accepted.
_BUDGET_CAP_KEYS = {
    "max_iterations": "iterations",
    "timeout_seconds": "wall_clock",
    "max_children": "children",
    "max_agents": "children",
    "max_workspace_bytes": "workspace_bytes",
    "max_messages_per_step": "messages_per_step",
    "iterations": "iterations",
    "wall_clock": "wall_clock",
    "children": "children",
    "workspace_bytes": "workspace_bytes",
    "messages_per_step": "messages_per_step",
}


def sanitize_budget(value: Any) -> Optional[float]:
    """A usable agent budget value, or None when unset/invalid (G-01).

    Agent-provided budgets are data, not authority: only a real number > 0
    tightens a limit. Wrong type (incl. bool) / None / NaN / <= 0 -> unset.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value:  # NaN never tightens anything
        return None
    if value <= 0:
        return None
    return value


def agent_budgets(engine: Any, agent_id: str) -> dict:
    """The agent's sanitized working budgets as ``{cap_name: value}``.

    Reads ``context.budgets`` from the agent's own workspace (ordinary
    data the agent may set, edit or delete mid-run) and maps budget keys
    onto cap names. Invalid values are dropped (treated as unset); when
    several keys map to one cap the smallest (tightest) wins. Never
    raises: a broken workspace must not break the watchdog.
    """
    try:
        ctx = engine.globals_for(agent_id).get("context")
    except Exception:  # noqa: BLE001 - the watchdog must never raise
        return {}
    budgets = getattr(ctx, "budgets", None)
    if not isinstance(budgets, dict):
        return {}
    out: dict = {}
    for key, value in budgets.items():
        cap = _BUDGET_CAP_KEYS.get(key) if isinstance(key, str) else None
        if cap is None:
            continue
        sanitized = sanitize_budget(value)
        if sanitized is None:
            continue
        current = out.get(cap)
        if current is None or sanitized < current:
            out[cap] = sanitized
    return out


def clamp_limit(ceiling: Any, budget: Any) -> tuple:
    """``min(agent_budget, ceiling)`` -> ``(effective_limit, source)``.

    The clamp (G-01): the ceiling ALWAYS comes from runtime settings; the
    agent budget only tightens. *source* is ``"agent_budget"`` when the
    agent's value is the binding limit, ``"ceiling"`` when the runtime's
    own limit binds (including the above-ceiling clamp case). A None
    ceiling means "no limit configured" — a budget then sets a working
    limit, which is still only a tightening.
    """
    if budget is None:
        return ceiling, "ceiling"
    if ceiling is None:
        return budget, "agent_budget"
    if budget <= ceiling:
        return budget, "agent_budget"
    return ceiling, "ceiling"


def cap_hit(
    agent_id: str,
    engine: Any,
    step_count: int,
    started_ts: float,
    *,
    settings: Any,
    child_count: Callable[[], int],
    pending_messages: Callable[[], int],
    parked_seconds: float = 0.0,
) -> Optional[dict]:
    """The first exceeded cap as ``{"cap", "limit", "source"}``, else None.

    The evaluation core (G-01): identical ceiling semantics to the
    historical watchdog, with the agent's working budgets
    (``context.budgets``) min-clamped onto each ceiling. ``limit`` is the
    EFFECTIVE limit (the binding value, after the clamp); ``source``
    names where it came from (``"agent_budget"`` / ``"ceiling"``).

    Parked time is credited against the wall clock (G-05, decision
    0008): time spent parked on ``yield Await(child)`` /
    ``yield Sleep(t)`` does not count against the effective limit —
    waiting on others consumes no agent budget (INFO-053). The credit is
    supplied by the pump (cumulative parked seconds); it never exceeds
    elapsed time.

    *child_count* and *pending_messages* are lazy thunks supplied by the
    caller (the runtime wrapper): they touch runtime state (the registry
    lock, the event-bus drain) and are invoked only when the corresponding
    cap is enabled — the drain must NOT run when the message-rate cap is
    disabled, or pending events would be consumed.
    """
    budgets = agent_budgets(engine, agent_id)
    # Wall clock (safety.timeout_seconds), parked time credited (0008).
    timeout_seconds, wall_src = clamp_limit(
        read_cap(settings, "timeout_seconds", _DEFAULT_TIMEOUT_SECONDS),
        budgets.get("wall_clock"),
    )
    if timeout_seconds is not None and (
        time.time() - started_ts - max(parked_seconds, 0.0) > timeout_seconds
    ):
        return {"cap": "wall_clock", "limit": timeout_seconds, "source": wall_src}
    # Step count (safety.max_iterations).
    max_iterations, iter_src = clamp_limit(
        read_cap(settings, "max_iterations", _DEFAULT_MAX_ITERATIONS),
        budgets.get("iterations"),
    )
    if max_iterations is not None and step_count >= max_iterations:
        return {"cap": "iterations", "limit": max_iterations, "source": iter_src}
    # Child count (safety.max_children, falling back to safety.max_agents).
    max_children, child_src = clamp_limit(
        read_cap(settings, "max_children", None)
        or read_cap(settings, "max_agents", _DEFAULT_MAX_CHILDREN),
        budgets.get("children"),
    )
    if max_children is not None:
        if child_count() >= max_children:
            return {"cap": "children", "limit": max_children, "source": child_src}
    # Workspace bytes (module constant unless settings provide one).
    max_workspace_bytes, ws_src = clamp_limit(
        read_cap(settings, "max_workspace_bytes", _DEFAULT_MAX_WORKSPACE_BYTES),
        budgets.get("workspace_bytes"),
    )
    if max_workspace_bytes is not None:
        try:
            ws = engine.globals_for(agent_id)
            size = sum(len(str(v)) for v in ws.values())
        except Exception:  # noqa: BLE001 - sizing is best-effort
            size = 0
        if size > max_workspace_bytes:
            return {
                "cap": "workspace_bytes",
                "limit": max_workspace_bytes,
                "source": ws_src,
            }
    # Message rate (module constant unless settings provide one).
    max_messages, msg_src = clamp_limit(
        read_cap(settings, "max_messages_per_step", _DEFAULT_MAX_MESSAGES_PER_STEP),
        budgets.get("messages_per_step"),
    )
    if max_messages is not None:
        if pending_messages() > max_messages:
            return {
                "cap": "messages_per_step",
                "limit": max_messages,
                "source": msg_src,
            }
    return None


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
    full config), with the agent's working budgets min-clamped onto each
    ceiling (G-01 — an agent budget can only tighten a limit). Tests force
    caps via a tiny settings object. Thin view over :func:`cap_hit`.
    """
    hit = cap_hit(
        agent_id,
        engine,
        step_count,
        started_ts,
        settings=settings,
        child_count=child_count,
        pending_messages=pending_messages,
        parked_seconds=parked_seconds,
    )
    return hit["cap"] if hit is not None else None
