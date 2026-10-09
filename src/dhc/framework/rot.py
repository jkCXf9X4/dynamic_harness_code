"""Agent-settable rot policy (G-06): the pump-side rot tripwire.

INFO-053 makes the agent's rot policy workspace data with a *reaction
surface*: the agent sets its own working rot policy as ordinary data
(``context.rot_policy``), and a trip surfaces as a completion-style event
on the parent's stream — the reaction runs in the parent's execution (the
A6 pattern), never in the child's.

The control split is preserved exactly:

* **Agent-owned** — the policy (threshold, action) is ordinary workspace
  data the agent reads and edits mid-run, like ``context.budgets`` (G-01).
* **Runtime-owned** — the *evaluation* runs here, in pump code between
  agent actions (R6): a degrading agent cannot skip its own leash. The
  agent's policy can only TIGHTEN the detector (a lower threshold) or
  ESCALATE the reaction (``observe`` -> ``escalate``); it can never loosen
  the default threshold, disable detection, or choose what the runtime does
  on a trip.

The default policy reproduces the historical detector behavior exactly:
observe-only. The detector itself (``ContextRotDetector``) is unchanged —
it still collects and logs rot signals on every generated block; the
driver additionally stashes the latest report on the agent (a
runtime-machinery rendezvous, like ``agent._last_result``) so the pump can
read it between steps without touching agent code.
"""

from __future__ import annotations

from typing import Any, Optional

#: The default rot threshold — ``ContextRotDetector``'s own default. The
#: agent's threshold is min-clamped to this: the agent can only tighten
#: (lower) the threshold, never loosen it (the ceiling always comes from
#: runtime code, never from agent data — R3's rot analogue).
DEFAULT_ROT_THRESHOLD = 0.6

#: The default reaction — the historical observe-only posture (INFO-021).
#: ``"escalate"`` is the only other accepted action: a trip then settles
#: the agent failed (containment) and surfaces on the parent's stream.
DEFAULT_ROT_ACTION = "observe"

#: The actions an agent policy may choose. ``"observe"`` is the default
#: (observe-only); ``"escalate"`` makes a trip a containment event.
_ROT_ACTIONS = ("observe", "escalate")


def sanitize_rot_policy(policy: Any) -> dict:
    """A usable rot policy dict, or ``{}`` when unset/invalid (G-06).

    Agent-provided policy values are data, not authority: only real
    numbers in ``(0, 1]`` tighten the threshold, and only the exact action
    strings are accepted. Wrong type (incl. bool) / None / NaN / out of
    range -> the key is dropped (treated as unset). The threshold is
    min-clamped to :data:`DEFAULT_ROT_THRESHOLD` by the caller
    (:func:`rot_trip`), not trusted here.
    """
    if not isinstance(policy, dict):
        return {}
    out: dict = {}
    threshold = policy.get("threshold")
    if (
        isinstance(threshold, (int, float))
        and not isinstance(threshold, bool)
        and threshold == threshold  # NaN never tightens anything
        and 0.0 < threshold <= 1.0
    ):
        out["threshold"] = float(threshold)
    action = policy.get("action")
    if isinstance(action, str) and action in _ROT_ACTIONS:
        out["action"] = action
    return out


def agent_rot_policy(engine: Any, agent_id: str) -> dict:
    """The agent's sanitized rot policy from ``context.rot_policy``.

    Reads the policy from the agent's own workspace (ordinary data the
    agent may set, edit or delete mid-run, exactly like
    ``context.budgets`` in G-01). Never raises: a broken workspace must
    not break the tripwire.
    """
    try:
        ctx = engine.globals_for(agent_id).get("context")
    except Exception:  # noqa: BLE001 - the tripwire must never raise
        return {}
    policy = getattr(ctx, "rot_policy", None)
    return sanitize_rot_policy(policy)


def rot_trip(agent: Any, engine: Any, agent_id: str) -> Optional[dict]:
    """The rot trip as ``{"score", "signals", "threshold", "action"}``, else None.

    The evaluation core (G-06), called by the pump between agent actions
    (R6). The effective threshold is ``min(agent_threshold,
    DEFAULT_ROT_THRESHOLD)`` — the agent can only tighten it, never loosen
    it. A trip requires BOTH:

    * the agent's policy escalates (``action == "escalate"``) — the default
      is observe-only, reproducing the historical detector behavior; and
    * the driver's latest rot report for this agent (stashed on the agent
      by ``LLMDriver.__call__``, the runtime-machinery rendezvous) scored
      at or above the effective threshold.

    Never raises: a missing report (no driver, a MockDriver, a fresh
    agent) simply means no trip.
    """
    policy = agent_rot_policy(engine, agent_id)
    if policy.get("action") != "escalate":
        return None  # observe-only: the default, and any unset/invalid policy
    report = getattr(agent, "_last_rot_report", None)
    if report is None or not getattr(report, "rot", False):
        return None
    threshold = policy.get("threshold")
    if threshold is None:
        threshold = DEFAULT_ROT_THRESHOLD
    else:
        # The ceiling always comes from runtime code: the agent can only
        # tighten (lower) the threshold, never loosen it.
        threshold = min(threshold, DEFAULT_ROT_THRESHOLD)
    score = getattr(report, "score", 0.0)
    if score < threshold:
        return None
    signals = getattr(report, "signals", None)
    return {
        "score": score,
        "signals": list(signals) if isinstance(signals, (list, tuple)) else [],
        "threshold": threshold,
        "action": "escalate",
    }
