"""G-02: prompt assembly as a workspace-swappable function (kit citizen).

Covers the roadmap item's four acceptance criteria:

1. ``build_prompt`` is a kit citizen installed in the workspace; the
   default is the doctrine prompt + the registry-generated API section
   (golden test — W1's deliberate change: the expected string below is
   the doctrine ``agent_system_prompt.txt`` plus the surface registry's
   generated core-tier section, so the prompt can never drift from the
   code).
2. An agent that replaces the workspace ``build_prompt`` changes the prompt
   the LLM receives (MockLLM asserts the new prompt text arrives).
3. ``prompts.py`` is no longer orphaned: its composition is explicitly
   superseded by the kit citizen (docstring corrected, no false claims).
4. ``examples/value_demo.py`` and the MockDriver suite pass unmodified
   (covered by their own tests; the golden test here guards the default).
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc.llm.driver import LLMDriver, MockDriver  # noqa: E402
from dhc.llm.llm import MockLLM  # noqa: E402
from dhc.tooling.fabrication import fabrication_kit  # noqa: E402
from dhc.wiring import build_runtime  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


# --------------------------------------------------------------------------- #
# The golden prompt: byte-identical to the pristine LLMDriver._build_prompt
# --------------------------------------------------------------------------- #


class _FakeAgent:
    """A minimal agent stand-in with the surface _build_prompt reads."""

    def __init__(self, requirement="do the thing", acceptance=("done",)):
        self.id = "golden-agent"
        self.requirement = requirement
        self.acceptance = tuple(acceptance)
        self._runtime = None

    def status(self):
        from dhc.data.models import Result

        return Result(done=False, ok=False, reason="not settled")


from dhc.llm.driver import _load_doctrine_prompt  # noqa: E402
from dhc.framework.surface import default_registry  # noqa: E402

#: The doctrine prompt (W1.5): the hand-written prose base.
_DOCTRINE = _load_doctrine_prompt().rstrip()

#: The registry-generated API section (W1.4): the single source of truth.
#: Computed INSIDE each test (not at module import): the registry is a
#: process-wide singleton whose entries are re-registered (idempotently)
#: when a runtime is wired — ``register_default_tools`` re-asserts the
#: Wave 3 tier moves and ``register_channel_tools`` re-registers its
#: entries — so an import-time snapshot can observe a pre-wiring state
#: that no longer matches what ``LLMDriver._build_prompt`` renders at
#: test time. Building the expected section per test keeps the golden
#: comparison about *drift*, not about import order.


def _expected_prompt() -> str:
    """The golden prompt, rendered from the registry at call time."""
    return (
        _DOCTRINE
        + "\n\n"
        + default_registry.prompt_section()
        + "\n\n"
        "Requirement: do the thing"
        "\n\n"
        "Acceptance criteria: ['done']"
        "\n\n"
        "Current status: done=False ok=False reason='not settled'"
    )


#: The byte-exact expected prompt for the fake agent above: the doctrine
#: prompt + the registry-generated API section + the per-agent state
#: (W1's deliberate golden change — see the module docstring). Any drift
#: in the doctrine file, the registry, or the assembly breaks this test.
#: Rendered per test via :func:`_expected_prompt` (the registry is a
#: process-wide singleton re-registered at wiring time — see the
#: :func:`_expected_prompt` note above).
GOLDEN_PROMPT = _expected_prompt()


def test_golden_default_prompt_is_byte_identical():
    """The default prompt assembly reproduces the pristine driver prompt.

    This is the back-compat gate: the kit citizen's default must be
    byte-identical to the pre-refactor ``LLMDriver._build_prompt`` output
    for the same agent state (no system prompt, no recent events).
    """
    agent = _FakeAgent()
    driver = LLMDriver(client=None)
    assert driver._build_prompt(agent) == _expected_prompt()


def test_golden_default_prompt_with_system_prompt_and_context():
    """Byte-identical with a system prompt and recent events, too."""
    from dhc.data.models import Result

    agent = _FakeAgent(requirement="ship it", acceptance=())
    agent._runtime = _FakeRuntime(
        events=[
            _FakeEvent("turn_started", {"code": "x = 1"}),
            _FakeEvent("turn_completed", {"ok": True}),
        ]
    )
    driver = LLMDriver(client=None, system_prompt="EXTRA GUIDANCE")
    expected = (
        "EXTRA GUIDANCE"
        "\n\n"
        + _DOCTRINE
        + "\n\n"
        + default_registry.prompt_section()
        + "\n\n"
        "Requirement: ship it"
        "\n\n"
        "Current status: done=False ok=False reason='not settled'"
        "\n\n"
        "Recent events:\n"
        "- turn_started: {\"code\": \"x = 1\"}\n"
        "- turn_completed: {\"ok\": true}"
    )
    assert driver._build_prompt(agent) == expected


class _FakeEvent:
    def __init__(self, kind, payload):
        self.kind = _FakeKind(kind)
        self.payload = payload


class _FakeKind:
    def __init__(self, value):
        self.value = value


class _FakeRuntime:
    def __init__(self, events):
        self._events = events

    def events(self, agent_id):
        return self._events


def test_golden_default_prompt_no_acceptance_no_context():
    """No acceptance, no events: the exact minimal prompt."""
    agent = _FakeAgent(requirement="minimal", acceptance=())
    driver = LLMDriver(client=None)
    expected = (
        _DOCTRINE
        + "\n\n"
        + default_registry.prompt_section()
        + "\n\n"
        "Requirement: minimal"
        "\n\n"
        "Current status: done=False ok=False reason='not settled'"
    )
    assert driver._build_prompt(agent) == expected


# --------------------------------------------------------------------------- #
# The kit citizen: build_prompt installed in the workspace
# --------------------------------------------------------------------------- #


def test_build_prompt_is_a_kit_citizen(tmp_path):
    """The fabrication kit installs ``build_prompt`` in the workspace."""
    from dhc.tooling.fabrication import FABRICATION_NAMES

    rt = build_runtime(mock=True, artifact_root=str(tmp_path))
    try:
        agent = _register_agent(rt)
        ns = rt._build_namespace(agent)
        assert "build_prompt" in FABRICATION_NAMES
        assert callable(ns["build_prompt"])
        # The default citizen reproduces the golden prompt byte-identically.
        fake = _FakeAgent()
        assert ns["build_prompt"](fake) == _expected_prompt()
    finally:
        rt.stop()


def test_agent_replacing_build_prompt_changes_the_llm_prompt(tmp_path):
    """G-02 criterion 2 (end-to-end through the pump): an agent that
    replaces the workspace ``build_prompt`` from workspace code changes
    the prompt the LLM receives.

    Turn 1: the LLM gets the DEFAULT prompt and returns a block that
    installs a custom assembly into the persistent ``state`` slot. Turn
    2: the LLM must receive the CUSTOM prompt.
    """
    seen = []

    def fake_llm(prompt, context=None):
        seen.append(prompt)
        if len(seen) == 1:
            # Turn 1: swap the prompt assembly from workspace code. The
            # state slot persists across the per-turn namespace refresh
            # (the same seam as state["_driver"]).
            return (
                "def _my_prompt(agent, driver=None):\n"
                "    return 'CUSTOM PROMPT: ' + agent.requirement\n"
                "state['build_prompt'] = _my_prompt\n"
            )
        return "result = complete('done')"

    rt = build_runtime(mock=True, artifact_root=str(tmp_path))
    try:
        root = rt.spawn(
            "observe the swap",
            acceptance=("done",),
            driver=LLMDriver(client=MockLLM(fn=fake_llm)),
        )
        comp = rt.await_(root.id)
        assert comp.status.value == "completed", comp.reason
        assert len(seen) == 2, f"expected two LLM calls, saw {len(seen)}"
        # Turn 1 carried the default assembly (the doctrine prompt)...
        assert seen[0].startswith("# Dynamic Harness Code (dhc)")
        assert "Requirement: observe the swap" in seen[0]
        # ...and turn 2 carried the agent's replacement.
        assert seen[1] == "CUSTOM PROMPT: observe the swap"
    finally:
        rt.stop()


def test_swapped_build_prompt_reaches_the_llm(tmp_path):
    """Unit-level: the workspace-name override is what the LLM sees."""
    from dhc.tooling.fabrication import fabrication_kit

    seen = []

    def fake_llm(prompt, context=None):
        seen.append(prompt)
        return "result = complete('done')"

    rt = build_runtime(mock=True, artifact_root=str(tmp_path))
    try:
        agent = _register_agent(rt, requirement="unit swap")
        engine = rt.repl_engine
        kit = fabrication_kit(rt, engine, agent)
        engine.inject(agent.id, kit)

        # The agent replaced its prompt assembly from workspace code: the
        # workspace name now holds the custom function.
        def custom(agent, driver=None):
            return "CUSTOM: " + agent.requirement

        engine.inject(agent.id, {"build_prompt": custom})
        driver = LLMDriver(client=MockLLM(fn=fake_llm))
        code = driver(agent)
        assert code == "result = complete('done')"
        assert seen == ["CUSTOM: unit swap"]
    finally:
        rt.stop()


def _register_agent(rt, agent_id="a1", requirement="r"):
    """Register an agent on the runtime WITHOUT starting a worker thread."""
    import threading

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
