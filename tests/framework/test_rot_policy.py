"""G-06: agent-settable rot policy as workspace data with a parent-side
reaction surface.

Acceptance criteria (roadmap G-06):

1. Rot thresholds/policy live in workspace data (``context.rot_policy``)
   the agent can read and edit; defaults reproduce current detector
   behavior exactly (observe-only).
2. A rot trip (under an agent policy that escalates) surfaces as a
   completion-style event on the parent's stream — the reaction runs in
   the parent's execution (A6); the child never executes its own
   termination.
3. The detector remains observe-only by default; no behavior change for
   existing tests.

The rot check runs in the pump, between agent actions (R6): a degrading
agent cannot skip its own leash. The agent's policy can only tighten the
threshold (min-clamped to the detector default) or escalate the action;
it can never loosen, disable, or choose the runtime's reaction.
"""

import threading

import pytest

from dhc.framework.rot import (
    DEFAULT_ROT_ACTION,
    DEFAULT_ROT_THRESHOLD,
    agent_rot_policy,
    rot_trip,
    sanitize_rot_policy,
)
from dhc.data.models import AgentStatus, EventKind
from dhc.llm.driver import LLMDriver, MockDriver
from dhc.tooling.fabrication import FabricationContext, fabrication_kit
from dhc.llm.llm import ContextRotDetector, RotReport


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _pumped_runtime(tmp_path, **settings_kwargs):
    """A fully-wired runtime (ReplEngine + fabrication kit) over tmp_path."""
    from dhc.data.config import Settings
    from dhc.wiring import build_runtime

    settings = Settings(
        workspace_root=tmp_path,
        artifact_root=tmp_path,
        **settings_kwargs,
    )
    rt = build_runtime(mock=True, artifact_root=tmp_path, settings=settings)
    rt.start()
    return rt


class _RottingClient:
    """Fake LLM client: returns one fixed block, no network."""

    def __init__(self, code):
        self._code = code

    def generate_code_block(self, prompt, context):
        return self._code


class _ReportingDriver:
    """A driver double that mimics LLMDriver's rot rendezvous.

    Scores each block with a real :class:`ContextRotDetector` and stashes
    the latest report on the agent (``agent._last_rot_report``) exactly as
    ``LLMDriver.__call__`` does — so the pump's tripwire sees it. Returns
    the block unchanged (observe-only at the driver seam).
    """

    def __init__(self, blocks, detector=None):
        self._blocks = list(blocks)
        self._calls = 0
        self._detector = detector or ContextRotDetector()
        self.reports = []

    def __call__(self, agent):
        if self._calls >= len(self._blocks):
            return None
        code = self._blocks[self._calls]
        self._calls += 1
        report = self._detector.observe(code)
        self.reports.append(report)
        agent._last_rot_report = report
        return code


# Valid-Python blocks that rot deterministically under the default
# detector (threshold 0.6): comments carrying >= 3 failure phrases score
# 0.75 via repeated_failure_phrases; a near-identical repeat scores 1.0
# via low_novelty.
_ROTTING_BLOCK = (
    "# error: failed\n"
    "# traceback: exception\n"
    "# sorry, i can't continue\n"
    "state['rot_mark'] = True\n"
)
_ROTTING_REPEAT = (
    "# error: failed\n"
    "# traceback: exception\n"
    "# sorry, i can't continue\n"
    "state['rot_mark_2'] = True\n"
)
# A clean block: normal prose comment, no failure phrases, novel tokens.
_CLEAN_BLOCK = (
    "# a perfectly ordinary progress note about zebras and kumquats\n"
    "state['clean_mark'] = True\n"
)


# --------------------------------------------------------------------------- #
# Criterion 1 — the policy is workspace data; defaults reproduce the detector
# --------------------------------------------------------------------------- #


def test_rot_policy_is_workspace_data(tmp_path):
    """G-06 (1): ``context.rot_policy`` is ordinary workspace data the
    agent reads and edits mid-run (same surface as ``context.budgets``)."""
    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn(
            "policy-holder",
            driver=MockDriver(
                [
                    "assert context.rot_policy == {}\n",
                    "context.rot_policy['action'] = 'escalate'\n"
                    "context.rot_policy['threshold'] = 0.5\n",
                    "assert context.rot_policy['action'] == 'escalate'\n",
                    "complete('policy edited')\n",
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        # The edit survived as ordinary workspace data.
        ws = rt.repl_engine.globals_for(handle.id)
        assert ws["context"].rot_policy == {"action": "escalate", "threshold": 0.5}
        # And is visible through the dict view the default decide reads.
        assert ws["context"].as_dict()["rot_policy"] == {
            "action": "escalate",
            "threshold": 0.5,
        }
    finally:
        rt.stop()


def test_rot_policy_defaults_reproduce_detector_behavior(tmp_path):
    """G-06 (1): with no policy set, the effective threshold/action are the
    detector's own defaults (0.6 / observe) — the historical posture."""
    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn(
            "defaults",
            driver=MockDriver(
                [
                    "assert context.rot_policy == {}\n",
                    "complete('no policy')\n",
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        ws = rt.repl_engine.globals_for(handle.id)
        policy = agent_rot_policy(rt.repl_engine, handle.id)
        assert policy == {}  # nothing set: pure default
        assert DEFAULT_ROT_THRESHOLD == ContextRotDetector().threshold
        assert DEFAULT_ROT_ACTION == "observe"
        # The default policy never trips, even on a rotting report.
        agent = rt.get(handle.id)
        agent._last_rot_report = RotReport(rot=True, score=1.0, signals=["repetition"])
        assert rot_trip(agent, rt.repl_engine, handle.id) is None
    finally:
        rt.stop()


def test_fabrication_context_carries_rot_policy():
    """The kit's context citizen exposes rot_policy backed by workspace
    state (survives namespace refreshes, like budgets)."""
    ctx = FabricationContext(agent_id="a1", state={})
    assert ctx.rot_policy == {}
    ctx.rot_policy["action"] = "escalate"
    assert ctx.state["rot_policy"] == {"action": "escalate"}
    assert ctx.as_dict()["rot_policy"] == {"action": "escalate"}


# --------------------------------------------------------------------------- #
# Criterion 3 — observe-only by default
# --------------------------------------------------------------------------- #


def test_rotting_context_observed_only_by_default(tmp_path):
    """G-06 (3): a rotting context under the DEFAULT policy is observed
    (the detector still collects and logs) but never trips: the agent
    completes normally, no crash event, no early settle."""
    rt = _pumped_runtime(tmp_path)
    try:
        driver = _ReportingDriver(
            [_ROTTING_BLOCK, _ROTTING_REPEAT, "complete('survived rot')\n"]
        )
        handle = rt.spawn("rotting-but-default", driver=driver)
        completion = handle.await_()
        # The detector observed rot (rotting blocks scored at/above the
        # default threshold) ...
        assert any(r.rot for r in driver.reports)
        # ... but the default policy is observe-only: no trip, no crash.
        assert completion.status == AgentStatus.completed
        assert completion.summary == "survived rot"
        crashes = [e for e in rt.events(handle.id) if e.kind == EventKind.crash]
        assert crashes == []
    finally:
        rt.stop()


def test_observe_action_is_observe_only(tmp_path):
    """An explicit ``action='observe'`` policy is also observe-only — the
    agent cannot use the policy to do anything but escalate."""
    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn(
            "explicit-observe",
            driver=MockDriver(
                [
                    "context.rot_policy['action'] = 'observe'\n",
                    _ROTTING_BLOCK,
                    "complete('still fine')\n",
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# Criterion 2 — an escalating policy trips from the pump, parent-side reaction
# --------------------------------------------------------------------------- #


def test_escalating_policy_trips_from_pump(tmp_path):
    """G-06 (2): the agent sets an escalating rot policy, its context
    rots, and the pump — not agent code — stops it: crash event naming the
    score/threshold, settle failed, the post-rot block never ran."""
    rt = _pumped_runtime(tmp_path)
    try:
        handle = rt.spawn(
            "escalating",
            driver=_ReportingDriver(
                [
                    "context.rot_policy['action'] = 'escalate'\n",
                    _ROTTING_BLOCK,
                    "state['after_rot'] = True\n",  # must never run
                    "complete('never reached')\n",
                ]
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.failed
        assert "context rot" in completion.reason
        # The block AFTER the rotting one never executed.
        ws = rt.repl_engine.globals_for(handle.id)
        assert "after_rot" not in ws["state"]
        # The trip surfaced as a crash event naming the rot payload.
        crashes = [
            e
            for e in rt.events(handle.id)
            if e.kind == EventKind.crash and "rot" in e.payload
        ]
        assert crashes, "expected a rot crash event"
        payload = crashes[0].payload
        assert payload["source"] == "agent_rot_policy"
        assert payload["rot"]["threshold"] == DEFAULT_ROT_THRESHOLD
        assert payload["rot"]["score"] >= payload["rot"]["threshold"]
        assert payload["rot"]["signals"]
        # The policy survived as ordinary workspace data.
        assert ws["context"].rot_policy == {"action": "escalate"}
    finally:
        rt.stop()


def test_rot_trip_surfaces_on_parent_stream_with_parent_side_reaction(tmp_path):
    """G-06 (2), the A6 pattern: a rotting child under an escalating
    policy surfaces as a completion-style event on the PARENT's stream;
    the reaction (cancel/settle bookkeeping) runs in the parent's worker
    loop via the on_done callback. The child never executes its own
    termination — its reaction IS the pump's settlement."""
    rt = _pumped_runtime(tmp_path)
    try:
        reactions = []
        parent = rt.spawn(
            "parent",
            driver=MockDriver(
                [
                    "c1 = spawn('rotting-child', driver=_child_driver, "
                    "on_done=lambda c: reactions.append((c.agent_id, c.status, c.reason)))\n"
                    "agent.await_(c1)\n"
                    "complete('parent done')\n",
                ]
            ),
            namespace={
                "reactions": reactions,
                "_child_driver": _ReportingDriver(
                    [
                        "context.rot_policy['action'] = 'escalate'\n",
                        _ROTTING_BLOCK,
                        "complete('never reached')\n",
                    ]
                ),
            },
        )
        parent.await_()
        child_id = rt.children_of(parent.id)[0]
        rt.await_(child_id)

        # The parent received the child's completion-style event on its
        # stream (the completion stream, in completion order).
        completions = rt.completions(parent.id)
        assert len(completions) == 1
        assert completions[0].agent_id == child_id
        assert completions[0].status == AgentStatus.failed
        assert "context rot" in completions[0].reason

        # The reaction ran in the PARENT's worker loop (the on_done
        # callback fired between the parent's actions, per A6).
        assert reactions == [
            (child_id, AgentStatus.failed, completions[0].reason)
        ]

        # The child never executed its own termination: it settled failed
        # via the pump's trip (never cancelled itself, never ran its own
        # post-rot block).
        child_ws = rt.repl_engine.globals_for(child_id)
        assert "rot_mark" in child_ws["state"]  # the rotting block ran
        assert "after_rot" not in child_ws["state"]  # the next one did not
        assert rt.poll(child_id) == AgentStatus.failed

        # The parent stayed alive and completed after the reaction.
        assert rt.poll(parent.id) == AgentStatus.completed
    finally:
        rt.stop()


def test_rot_trip_fires_though_agent_code_never_checks_it(tmp_path):
    """R6 mirror of test_d5b: the trip fires from the pump's between-step
    gate even though the agent's code never consults the rot policy or the
    detector — a degrading agent cannot skip its own leash."""
    rt = _pumped_runtime(tmp_path)
    try:
        # The policy is pre-seeded via the namespace (not by agent code):
        # the agent's blocks are pure rot, never checking anything.
        def _seed_policy(agent):
            ctx = rt.repl_engine.globals_for(agent.id).get("context")
            if ctx is not None:
                ctx.rot_policy["action"] = "escalate"
            return "state['first'] = True\n"

        handle = rt.spawn(
            "unchecked",
            driver=_SeedThenRotDriver(
                seed=_seed_policy,
                blocks=[_ROTTING_BLOCK, "complete('never reached')\n"],
            ),
        )
        completion = handle.await_()
        assert completion.status == AgentStatus.failed
        assert "context rot" in completion.reason
    finally:
        rt.stop()


class _SeedThenRotDriver:
    """Seeds the policy on the first call, then replays rotting blocks."""

    def __init__(self, seed, blocks):
        self._seed = seed
        self._blocks = list(blocks)
        self._calls = 0
        self._detector = ContextRotDetector()

    def __call__(self, agent):
        if self._calls == 0:
            self._calls += 1
            return self._seed(agent)
        if self._calls > len(self._blocks):
            return None
        code = self._blocks[self._calls - 1]
        self._calls += 1
        report = self._detector.observe(code)
        agent._last_rot_report = report
        return code


# --------------------------------------------------------------------------- #
# Sanitization — agent data can only tighten/escalate, never disable
# --------------------------------------------------------------------------- #


def test_threshold_only_tightens():
    """An above-default threshold is clamped to the default: the agent can
    only tighten (lower) the threshold, never loosen it."""
    policy = sanitize_rot_policy({"action": "escalate", "threshold": 0.9})
    assert policy["threshold"] == 0.9  # sanitized as given ...
    # ... but the trip evaluation min-clamps to the default.
    class _Agent:
        _last_rot_report = RotReport(rot=True, score=0.75, signals=["repetition"])

    class _Engine:
        def globals_for(self, agent_id):
            return {"context": _Ctx({"action": "escalate", "threshold": 0.9})}

    trip = rot_trip(_Agent(), _Engine(), "a1")
    assert trip is not None
    assert trip["threshold"] == DEFAULT_ROT_THRESHOLD  # clamped, not loosened
    assert trip["score"] == 0.75


class _Ctx:
    def __init__(self, policy):
        self.rot_policy = policy


def test_invalid_policy_values_fall_back_to_defaults():
    """Wrong type / None / NaN / out-of-range / unknown action -> the key
    is dropped; the policy can never disable the runtime's guarantees."""
    bad_policies = [
        None,
        "escalate",
        42,
        [],
        {"threshold": None},
        {"threshold": "0.5"},
        {"threshold": True},
        {"threshold": 0},
        {"threshold": -0.1},
        {"threshold": 1.5},
        {"threshold": float("nan")},
        {"action": None},
        {"action": "terminate"},  # not an accepted action
        {"action": "ESCALATE"},  # exact strings only
        {"action": 1},
    ]
    for policy in bad_policies:
        sanitized = sanitize_rot_policy(policy)
        # No invalid value produces an escalating action or a threshold.
        assert sanitized.get("action") is None
        assert sanitized.get("threshold") is None
    # The one valid escalating action survives sanitization.
    assert sanitize_rot_policy({"action": "escalate"}) == {"action": "escalate"}


def test_agent_rot_policy_never_raises():
    """A broken workspace must not break the tripwire."""

    class _Boom:
        def globals_for(self, agent_id):
            raise RuntimeError("workspace gone")

    assert agent_rot_policy(_Boom(), "a1") == {}

    class _NoContext:
        def globals_for(self, agent_id):
            return {}

    assert agent_rot_policy(_NoContext(), "a1") == {}

    class _Weird:
        def globals_for(self, agent_id):
            return {"context": object()}  # no rot_policy attr

    assert agent_rot_policy(_Weird(), "a1") == {}


def test_rot_trip_tolerates_missing_report():
    """No report (fresh agent, MockDriver, no detector) -> no trip, even
    under an escalating policy."""

    class _Engine:
        def globals_for(self, agent_id):
            return {"context": _Ctx({"action": "escalate"})}

    class _NoReport:
        pass

    assert rot_trip(_NoReport(), _Engine(), "a1") is None

    class _NotRot:
        _last_rot_report = RotReport(rot=False, score=0.1, signals=[])

    assert rot_trip(_NotRot(), _Engine(), "a1") is None


def test_below_threshold_score_does_not_trip():
    """A report below the effective threshold does not trip (the agent
    tightened to 0.5; a 0.4 score survives)."""

    class _Engine:
        def globals_for(self, agent_id):
            return {"context": _Ctx({"action": "escalate", "threshold": 0.5})}

    class _Low:
        _last_rot_report = RotReport(rot=True, score=0.4, signals=["repetition"])

    assert rot_trip(_Low(), _Engine(), "a1") is None


# --------------------------------------------------------------------------- #
# The real driver seam — the rendezvous is the production path
# --------------------------------------------------------------------------- #


def test_llm_driver_stashes_rot_report_on_agent(tmp_path, monkeypatch):
    """The real LLMDriver (not a double) stashes its latest RotReport on
    the agent — the rendezvous the pump reads. Observe-only: the block is
    returned unchanged."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    from dhc.wiring import build_runtime

    rt = build_runtime(mock=False, artifact_root=str(tmp_path))
    try:
        agent = _register_agent(rt)
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        driver = kit["state"]["_driver"]
        assert isinstance(driver, LLMDriver)
        driver._client = _RottingClient(_ROTTING_BLOCK)
        code = driver(agent)
        assert code == _ROTTING_BLOCK  # observe-only: unchanged
        report = agent._last_rot_report
        assert isinstance(report, RotReport)
        assert report.rot is True
        assert report.score >= DEFAULT_ROT_THRESHOLD
        # The wired detector collected the block (unchanged behavior).
        assert list(driver._rot_detector._window) == [_ROTTING_BLOCK]
    finally:
        rt.stop()


def _register_agent(rt, agent_id="a1", requirement="r"):
    """Register an agent on the runtime WITHOUT starting a worker thread
    (the same bookkeeping spawn does, minus the thread)."""
    from dhc.framework.agent import Agent, AgentHandle

    agent = Agent(
        id=agent_id,
        requirement=requirement,
        runtime=rt,
    )
    rt._agents[agent_id] = agent
    rt._handles[agent_id] = AgentHandle(agent_id, rt)
    rt._stop_flags[agent_id] = threading.Event()
    return agent


# --------------------------------------------------------------------------- #
# End-to-end through the REAL LLMDriver + pump (the production path)
# --------------------------------------------------------------------------- #


def test_escalating_policy_trips_through_real_llm_driver(tmp_path, monkeypatch):
    """The full production path: a real LLMDriver (spy client) generates a
    rotting block; the driver's rendezvous + the pump's tripwire stop the
    agent under an escalating policy — and the parent's stream receives
    the completion."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    from dhc.data.config import Settings
    from dhc.wiring import build_runtime

    settings = Settings(workspace_root=tmp_path, artifact_root=tmp_path)
    rt = build_runtime(mock=False, artifact_root=tmp_path, settings=settings)
    rt.start()
    try:
        # A real LLMDriver whose client returns rotting blocks. The first
        # block sets the escalating policy; the second rots.
        driver = LLMDriver(
            _SequenceClient(
                [
                    "context.rot_policy['action'] = 'escalate'\n",
                    _ROTTING_BLOCK,
                    "complete('never reached')\n",
                ]
            ),
            rot_detector=ContextRotDetector(),
        )
        handle = rt.spawn("real-path", driver=driver)
        completion = handle.await_()
        assert completion.status == AgentStatus.failed
        assert "context rot" in completion.reason
        crashes = [
            e
            for e in rt.events(handle.id)
            if e.kind == EventKind.crash and "rot" in e.payload
        ]
        assert crashes
        assert crashes[0].payload["source"] == "agent_rot_policy"
    finally:
        rt.stop()


class _SequenceClient:
    """Fake LLM client returning a fixed sequence of blocks."""

    def __init__(self, blocks):
        self._blocks = list(blocks)
        self._calls = 0

    def generate_code_block(self, prompt, context):
        if self._calls >= len(self._blocks):
            return None
        code = self._blocks[self._calls]
        self._calls += 1
        return code
