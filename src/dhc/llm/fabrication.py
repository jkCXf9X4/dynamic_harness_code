"""The fabrication kit (IMP-001 D4): default ``__runner`` + ``decide(context)``.

Every workspace is born with a fabrication kit whose defaults replicate
today's behavior exactly:

* ``__runner`` — the default agent loop as a resumable generator, authored as
  workspace code (a string) so the agent can view/edit/replace it. It lives in
  the agent's own workspace globals as ``__runner``.
* ``decide(context)`` — the default decide fabrication wrapping the current
  LLM/Mock brain; ``driver.__call__`` becomes the default decide and its
  bookkeeping (``_turns``/``_calls``) moves into workspace state.
* ``run_block`` — non-locking nested exec against the workspace.
* ``build_prompt`` — the default prompt assembly (G-02): a kit citizen
  wrapping the byte-identical extraction of the historical
  ``LLMDriver._build_prompt``; an agent that replaces it changes the prompt
  the LLM receives.
* ``context`` — guardrails/inbox/outbox/budgets/digests as ordinary workspace
  data (full transparency, D2).
* channel handles (``messenger``, ``room``, ``escalate``, ``ask``).
* checkpoint/rollback/compact helpers and a visible caps view.
* ``ensure_fabrication`` — re-seeds any fabrication the agent broke or deleted
  (e.g. ``__runner = 42`` -> re-seed the default; event emitted).

The kit is installable and testable WITHOUT the pump (Step 3 rewrites
``runtime.py``): ``wiring.py`` injects it into the namespace, and tests drive
the default ``__runner`` directly through ``ReplEngine.advance``.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from ..framework.context import make_observe as _context_make_observe
from .driver import default_build_prompt, driver_from_settings
from ..data.models import AgentStatus, EventKind

#: The default agent loop, authored as workspace code (IMP-001 D4).
#: The agent views/edits/replaces this string in its own workspace globals.
DEFAULT_RUNNER_SOURCE = '''\
def __runner__(ctx):
    """Default agent loop (IMP-001 D4): decide -> run_block -> settle.

    Replicates today's turn loop exactly: decide the next block, run it,
    consume happenings, settle. Yields after each turn so the pump can
    checkpoint between steps.
    """
    while True:
        code = ctx["decide"](ctx)
        if code is None:
            ctx["settle"]()
            return
        ctx["run_block"](code)
        ctx["observe"]()
        if ctx["acceptance_met"]():
            ctx["settle_completed"]()
            return
        yield "step"
'''

#: The fabrication names the kit installs (and ``ensure_fabrication`` guards).
FABRICATION_NAMES: tuple[str, ...] = (
    "__runner",
    "decide",
    "run_block",
    "context",
    "ensure_fabrication",
    "checkpoint",
    "rollback",
    "compact",
    "caps",
    "build_prompt",
)


class FabricationContext:
    """The ``context`` workspace citizen (IMP-001 D4).

    Carries the agent's guardrails, inbox, outbox, budgets, rot policy and
    digests as ordinary workspace data (full transparency, D2), plus the
    workspace state dict the default ``decide`` fabrication uses for its
    bookkeeping (``_turns``/``_calls`` moved into workspace state).
    """

    def __init__(
        self,
        agent_id: str,
        runtime: Any = None,
        engine: Any = None,
        state: Optional[dict] = None,
    ) -> None:
        self.agent_id = agent_id
        self.runtime = runtime
        self.engine = engine
        self.state = state if state is not None else {}
        self.guardrails = self.state.setdefault("guardrails", {})
        self.inbox = self.state.setdefault("inbox", [])
        self.outbox = self.state.setdefault("outbox", [])
        self.budgets = self.state.setdefault("budgets", {})
        self.rot_policy = self.state.setdefault("rot_policy", {})
        self.digests = self.state.setdefault("digests", {})

    def as_dict(self) -> dict:
        """The dict view the default decide fabrication reads."""
        return {
            "agent_id": self.agent_id,
            "agent": self.runtime.get(self.agent_id) if self.runtime else None,
            "state": self.state,
            "guardrails": self.guardrails,
            "inbox": self.inbox,
            "outbox": self.outbox,
            "budgets": self.budgets,
            "rot_policy": self.rot_policy,
            "digests": self.digests,
        }


# -- decide ---------------------------------------------------------------- #


def make_decide(driver: Any, agent: Any, state: dict) -> Callable[[Any], Optional[str]]:
    """The default decide fabrication: *driver*.__call__ over workspace state.

    ``driver.__call__`` becomes the default decide (D4): given a context (the
    :class:`FabricationContext` or a dict), it returns the next code block or
    ``None`` to settle. Its bookkeeping (``_turns``/``_calls``) lives in
    ``state`` — workspace state, not driver attributes. The *driver* object
    itself is also kept in ``state`` (``_driver``) so a namespace refresh
    between steps does not reset a scripted MockDriver's position, and so an
    agent can swap its brain by replacing ``state["_driver"]``.
    """

    def decide(ctx: Any) -> Optional[str]:
        d = ctx.as_dict() if hasattr(ctx, "as_dict") else dict(ctx)
        d.setdefault("agent", agent)
        d.setdefault("state", state)
        state["_turns"] = state.get("_turns", 0) + 1
        state["_calls"] = state.get("_calls", 0) + 1
        brain = state.get("_driver", driver)
        return brain(d["agent"])

    return decide


# -- build_prompt (G-02: prompt assembly as a workspace citizen) ------------ #
#
# The kit citizen is ``default_build_prompt`` itself (the byte-identical
# extraction of the historical ``LLMDriver._build_prompt``): the agent can
# read its own default assembly source directly. An agent swaps prompt
# assembly by replacing it — either the workspace name (honored until the
# next per-turn namespace refresh) or, persistently, the
# ``state["build_prompt"]`` slot (the same seam as ``state["_driver"]``;
# the state dict survives the refresh). The driver resolves both before
# falling back to the default; see ``LLMDriver._build_prompt``.


# -- run_block ------------------------------------------------------------- #


def make_run_block(
    engine: Any, agent_id: str, namespace_builder: Callable[[], dict]
) -> Callable[..., Any]:
    """Bound ``run_block``: non-locking nested exec against the workspace.

    Refreshes the in-code surface (the namespace) into the workspace before
    each exec — the same per-turn refresh the committed runtime does — so a
    block sees ``publish``/``complete``/``agent``/... even when the default
    ``__runner`` is driven directly through ``ReplEngine.advance`` without
    the pump.
    """

    def run_block(code: str, timeout: Optional[float] = None) -> Any:
        engine.inject_nolock(agent_id, namespace_builder())
        return engine.run_block(agent_id, code, timeout)

    return run_block


# -- observe / settle (the default loop's consume-happenings step) --------- #


def make_observe(
    runtime: Any, agent_id: str, state: dict
) -> Callable[[], list]:
    """Consume happenings: completion callbacks + the event-stream digest.

    Thin delegate to :mod:`dhc.framework.context` (the context-trigger seam);
    identical semantics: drain, extend the workspace digest, trim to the
    last 50 entries.
    """
    return _context_make_observe(
        lambda: runtime._drain_completions(agent_id),
        lambda: runtime.events(agent_id),
        state,
    )


def make_settle(runtime: Any, agent_id: str) -> Callable[[], None]:
    """Settle by the last result, honoring parent liveness (INFO-014)."""

    def settle() -> None:
        if not runtime._wait_children_settled(agent_id):
            return  # cancelled while waiting
        runtime._drain_completions(agent_id)
        agent = runtime.get(agent_id)
        last_result = agent._last_result
        if last_result is not None and last_result.ok:
            runtime._settle(
                agent_id,
                AgentStatus.completed,
                summary=str(last_result.value or ""),
            )
        else:
            reason = last_result.reason if last_result is not None else "no result"
            runtime._settle(agent_id, AgentStatus.failed, reason=reason)

    return settle


def make_acceptance_met(runtime: Any, agent_id: str) -> Callable[[], bool]:
    """True when the agent's acceptance criteria are met by the last turn."""

    def acceptance_met() -> bool:
        agent = runtime.get(agent_id)
        return (
            bool(agent.acceptance)
            and agent._last_result is not None
            and agent._last_result.ok
        )

    return acceptance_met


def make_settle_completed(runtime: Any, agent_id: str) -> Callable[[], None]:
    """Settle the agent as completed with the last result's value."""

    def settle_completed() -> None:
        agent = runtime.get(agent_id)
        summary = (
            str(agent._last_result.value or "")
            if agent._last_result is not None
            else ""
        )
        runtime._settle(agent_id, AgentStatus.completed, summary=summary)

    return settle_completed


# -- checkpoint / rollback / compact --------------------------------------- #


def make_checkpoint(
    engine: Any, agent_id: str, state: dict
) -> Callable[..., int]:
    """Record a workspace snapshot in the context's checkpoint log.

    This is the **agent's own** checkpoint mechanism (decision 0012, H-06):
    in-workspace, in-memory, ordinary data the agent reads and writes freely.
    It is distinct from the operator's on-disk ``CheckpointStore``
    (``dhc.ui.checkpoint``), which is the operator's resumability
    mechanism surfaced via the terminal's ``/resume`` and is deliberately
    outside the agent's context. The two are independent; see
    ``decisions/0012-h06-checkpoint-split.md``.
    """

    def checkpoint(note: str = "", done: tuple = ()) -> int:
        log = state.setdefault("checkpoints", [])
        log.append(
            {
                "note": note,
                "done": list(done),
                "snapshot": dict(engine.globals_for(agent_id)),
            }
        )
        return len(log) - 1

    return checkpoint


def make_rollback(
    engine: Any, agent_id: str, state: dict
) -> Callable[..., bool]:
    """Restore the workspace to a checkpoint (best-effort merge)."""

    def rollback(index: Optional[int] = None) -> bool:
        log = state.get("checkpoints", [])
        if not log:
            return False
        snap = log[index if index is not None else -1]["snapshot"]
        engine.inject(agent_id, snap)
        return True

    return rollback


def make_compact(engine: Any, agent_id: str) -> Callable[[], list]:
    """Drop transient workspace names (the per-turn result slot)."""

    def compact() -> list:
        ws = engine.globals_for(agent_id)
        removed = [name for name in ("result",) if name in ws]
        for name in removed:
            engine.inject(agent_id, {name: None})
        return removed

    return compact


# -- caps view ------------------------------------------------------------- #


def make_caps(runtime: Any, agent_id: str) -> Callable[[], dict]:
    """A visible view of the outer ceiling caps (D2)."""

    def caps() -> dict:
        settings = runtime.settings
        safety = settings.config.safety if settings and settings.config else None
        return {
            "wall_clock_seconds": safety.timeout_seconds if safety else None,
            "max_iterations": safety.max_iterations if safety else None,
            "max_agents": safety.max_agents if safety else None,
            "max_depth": safety.max_depth if safety else None,
            # IMP-001 Step 5: the ceiling caps (per-agent; None = runtime
            # default) — the reportable caps digest.
            "max_workspace_bytes": safety.max_workspace_bytes if safety else None,
            "max_children": safety.max_children if safety else None,
            "max_messages_per_step": safety.max_messages_per_step if safety else None,
            "max_turn_seconds": runtime._max_turn_seconds(),
            "children": len(runtime.children_of(agent_id)),
        }

    return caps


# -- ensure_fabrication ---------------------------------------------------- #


def make_ensure_fabrication(
    runtime: Any,
    engine: Any,
    agent: Any,
    kit_builder: Callable[[], dict],
) -> Callable[[], list]:
    """Re-seed any fabrication the agent broke or deleted (D4).

    Validates every workspace citizen in :data:`FABRICATION_NAMES` against
    the kit's canonical copies and re-seeds the broken/missing ones from the
    kit, re-installing the engine-side runner when ``__runner`` was broken.
    Emits a ``fabrication_reseeded`` crash event naming the re-seeded
    citizens when anything was re-seeded.

    The self-guard case: the pump calls this kit-owned closure (via
    :mod:`dhc.framework.integrity`), never the workspace copy, so a broken
    workspace ``ensure_fabrication`` is itself re-seedable without recursion
    or dependence on the broken copy.
    """

    def ensure_fabrication() -> list:
        agent_id = agent.id
        reseeded: list[str] = []
        # A workspace that has never been seeded (no turn yet) needs no
        # re-seed: the first namespace build installs the kit. Only re-seed
        # when the agent has a workspace and broke/deleted a citizen.
        if not engine.has_workspace(agent_id):
            return reseeded
        ws = engine.globals_for(agent_id)

        runner = ws.get("__runner")
        if not isinstance(runner, str):
            kit = kit_builder()
            engine.inject(agent_id, {"__runner": DEFAULT_RUNNER_SOURCE})
            engine.install(agent_id, make_default_runner(engine, agent_id, kit))
            reseeded.append("__runner")

        ctx = ws.get("context")
        if not isinstance(ctx, FabricationContext):
            kit = kit_builder()
            engine.inject(agent_id, {"context": kit["context"]})
            reseeded.append("context")

        dec = ws.get("decide")
        if not callable(dec):
            kit = kit_builder()
            engine.inject(agent_id, {"decide": kit["decide"]})
            reseeded.append("decide")

        rb = ws.get("run_block")
        if not callable(rb):
            kit = kit_builder()
            engine.inject(agent_id, {"run_block": kit["run_block"]})
            reseeded.append("run_block")

        bp = ws.get("build_prompt")
        if not callable(bp):
            kit = kit_builder()
            engine.inject(agent_id, {"build_prompt": kit["build_prompt"]})
            reseeded.append("build_prompt")

        # The 5 previously-unguarded citizens (G-03): validated against the
        # kit's canonical copies and re-seeded from the kit. The self-guard
        # case — a broken workspace ``ensure_fabrication`` — is handled here
        # because the pump invokes THIS kit-owned closure, never the
        # workspace copy, so re-seeding it needs no recursion and no
        # dependence on the broken copy.
        ef = ws.get("ensure_fabrication")
        if not callable(ef):
            kit = kit_builder()
            engine.inject(agent_id, {"ensure_fabrication": kit["ensure_fabrication"]})
            reseeded.append("ensure_fabrication")

        cp = ws.get("checkpoint")
        if not callable(cp):
            kit = kit_builder()
            engine.inject(agent_id, {"checkpoint": kit["checkpoint"]})
            reseeded.append("checkpoint")

        rbk = ws.get("rollback")
        if not callable(rbk):
            kit = kit_builder()
            engine.inject(agent_id, {"rollback": kit["rollback"]})
            reseeded.append("rollback")

        cm = ws.get("compact")
        if not callable(cm):
            kit = kit_builder()
            engine.inject(agent_id, {"compact": kit["compact"]})
            reseeded.append("compact")

        cv = ws.get("caps")
        if not callable(cv):
            kit = kit_builder()
            engine.inject(agent_id, {"caps": kit["caps"]})
            reseeded.append("caps")

        if reseeded:
            runtime._emit(
                agent_id,
                EventKind.crash,
                payload={"fabrication_reseeded": reseeded},
            )
        return reseeded

    return ensure_fabrication


# -- the kit --------------------------------------------------------------- #


def make_default_runner(engine: Any, agent_id: str, kit: dict) -> Any:
    """Build the default ``__runner`` generator from the workspace source."""
    ns: dict = {"__builtins__": __builtins__}
    exec(
        compile(DEFAULT_RUNNER_SOURCE, f"<default-runner:{agent_id}>", "exec"),
        ns,
    )
    return ns["__runner__"](kit)


def fabrication_kit(runtime: Any, engine: Any, agent: Any) -> dict:
    """Build the fabrication kit for one agent (IMP-001 D4).

    Returns the namespace additions AND the runner's context (the kit dict
    doubles as the ``ctx`` the default ``__runner`` generator reads).

    The decide bookkeeping state is reused from the workspace when the agent
    already has a ``context`` (so a namespace refresh between steps does not
    reset ``_turns``/``_calls``).
    """
    agent_id = agent.id
    state: dict = {}
    if engine is not None and engine.has_workspace(agent_id):
        existing = engine.globals_for(agent_id).get("context")
        if isinstance(existing, FabricationContext):
            state = existing.state

    driver = state.get("_driver")
    if driver is None:
        driver = driver_from_settings(
            mock=getattr(runtime, "mock", False),
            rot_detector=getattr(runtime, "rot_detector", None),
        )
        state["_driver"] = driver
    decide = make_decide(driver, agent, state)
    run_block = make_run_block(
        engine, agent_id, lambda: runtime._build_namespace(agent)
    )
    observe = make_observe(runtime, agent_id, state)
    settle = make_settle(runtime, agent_id)
    acceptance_met = make_acceptance_met(runtime, agent_id)
    settle_completed = make_settle_completed(runtime, agent_id)
    context = FabricationContext(
        agent_id=agent_id, runtime=runtime, engine=engine, state=state
    )
    kit_builder: Callable[[], dict] = lambda: fabrication_kit(runtime, engine, agent)
    ensure_fabrication = make_ensure_fabrication(
        runtime, engine, agent, kit_builder
    )
    checkpoint = make_checkpoint(engine, agent_id, state)
    rollback = make_rollback(engine, agent_id, state)
    compact = make_compact(engine, agent_id)
    caps = make_caps(runtime, agent_id)
    return {
        "__runner": DEFAULT_RUNNER_SOURCE,
        "decide": decide,
        "run_block": run_block,
        "context": context,
        "ensure_fabrication": ensure_fabrication,
        "checkpoint": checkpoint,
        "rollback": rollback,
        "compact": compact,
        "caps": caps,
        # G-02: prompt assembly as a workspace citizen. The default IS the
        # byte-identical extraction of the historical LLMDriver._build_prompt
        # (the agent can read its own default assembly source directly). An
        # agent swaps it by replacing the workspace name or, persistently,
        # state["build_prompt"] — the same seam as state["_driver"].
        "build_prompt": default_build_prompt,
        # The runner's context (also namespace citizens; harmless extras):
        "state": state,
        "observe": observe,
        "settle": settle,
        "acceptance_met": acceptance_met,
        "settle_completed": settle_completed,
    }