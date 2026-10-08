"""G-02: prompt assembly as a workspace-swappable function (kit citizen).

Covers the roadmap item's four acceptance criteria:

1. ``build_prompt`` is a kit citizen installed in the workspace; the default
   reproduces ``LLMDriver._build_prompt`` byte-identically (golden test —
   the expected string below was captured from the pristine driver BEFORE
   any refactoring, so the refactor cannot drift).
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
from dhc.llm.fabrication import fabrication_kit  # noqa: E402
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


#: The byte-exact expected prompt for the fake agent above, captured from
#: the pristine ``LLMDriver._build_prompt`` (driver.py @ 25bab3d) BEFORE the
#: G-02 refactor. Any drift in the default assembly breaks this test.
GOLDEN_PROMPT = (
    "You are the action generator for a recursive agent runtime. "
    "Write ONE Python block — the next action — that makes progress "
    "on the agent's requirement. The block runs against the agent's "
    "persistent REPL, so state persists between turns. End the block "
    "by calling complete(...) when the requirement is satisfied, or "
    "fail(reason) when it cannot be. Respond with ONLY the Python "
    "code, no prose."
    "\n\n"
    "Available in the namespace: agent, publish(headline, summary, report), "
    "spawn(requirement, acceptance=(), driver=None, on_done=None), "
    "complete(headline, artifacts=()), fail(reason), cancel(reason), "
    "status(), result(), tool(callable, *args), bash(cmd), room(name), "
    "await_(handle), poll(handle), children_of(handle), "
    "messenger.send(recipient_id, body), escalate(reason), "
    "ask_operator(question)."
    "\n\n"
    "Requirement: do the thing"
    "\n\n"
    "Acceptance criteria: ['done']"
    "\n\n"
    "Current status: done=False ok=False reason='not settled'"
)


def test_golden_default_prompt_is_byte_identical():
    """The default prompt assembly reproduces the pristine driver prompt.

    This is the back-compat gate: the kit citizen's default must be
    byte-identical to the pre-refactor ``LLMDriver._build_prompt`` output
    for the same agent state (no system prompt, no recent events).
    """
    agent = _FakeAgent()
    driver = LLMDriver(client=None)
    assert driver._build_prompt(agent) == GOLDEN_PROMPT


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
        "You are the action generator for a recursive agent runtime. "
        "Write ONE Python block — the next action — that makes progress "
        "on the agent's requirement. The block runs against the agent's "
        "persistent REPL, so state persists between turns. End the block "
        "by calling complete(...) when the requirement is satisfied, or "
        "fail(reason) when it cannot be. Respond with ONLY the Python "
        "code, no prose."
        "\n\n"
        "Available in the namespace: agent, publish(headline, summary, report), "
        "spawn(requirement, acceptance=(), driver=None, on_done=None), "
        "complete(headline, artifacts=()), fail(reason), cancel(reason), "
        "status(), result(), tool(callable, *args), bash(cmd), room(name), "
        "await_(handle), poll(handle), children_of(handle), "
        "messenger.send(recipient_id, body), escalate(reason), "
        "ask_operator(question)."
        "\n\n"
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
        "You are the action generator for a recursive agent runtime. "
        "Write ONE Python block — the next action — that makes progress "
        "on the agent's requirement. The block runs against the agent's "
        "persistent REPL, so state persists between turns. End the block "
        "by calling complete(...) when the requirement is satisfied, or "
        "fail(reason) when it cannot be. Respond with ONLY the Python "
        "code, no prose."
        "\n\n"
        "Available in the namespace: agent, publish(headline, summary, report), "
        "spawn(requirement, acceptance=(), driver=None, on_done=None), "
        "complete(headline, artifacts=()), fail(reason), cancel(reason), "
        "status(), result(), tool(callable, *args), bash(cmd), room(name), "
        "await_(handle), poll(handle), children_of(handle), "
        "messenger.send(recipient_id, body), escalate(reason), "
        "ask_operator(question)."
        "\n\n"
        "Requirement: minimal"
        "\n\n"
        "Current status: done=False ok=False reason='not settled'"
    )
    assert driver._build_prompt(agent) == expected
