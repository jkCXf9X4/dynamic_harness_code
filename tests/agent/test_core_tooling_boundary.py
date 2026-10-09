"""The framework core must stay store-unaware and channel-unaware (0014/0015).

The artifact store and the communication channels are operator tooling
(``dhc.tooling``); the framework core (``dhc.agent``) knows artifacts only
as opaque ids on ``Result``/``Completion`` and the ``artifact_published``
event kind, and knows communication only as the directed-message primitive
(``Runtime.send`` / ``Agent.send``) and the ``message_sent`` event kind.
This test locks the dependency direction: no module under ``dhc.agent`` may
import ``dhc.tooling``.
"""

import importlib
import pkgutil
import sys

import dhc.agent
import dhc.tooling  # noqa: F401 - ensures the package imports cleanly


def _import_all_agent_modules() -> None:
    """Import every module under ``dhc.agent`` (walk includes submodules)."""
    for mod in pkgutil.walk_packages(dhc.agent.__path__, prefix="dhc.agent."):
        importlib.import_module(mod.name)


def _tooling_leaks() -> list[tuple[str, str]]:
    """(module, attribute) pairs where a dhc.agent module holds a value whose
    defining module lives under dhc.tooling — i.e. a tooling import."""
    leaks: list[tuple[str, str]] = []
    for name, mod in sys.modules.items():
        if not name.startswith("dhc.agent"):
            continue
        for attr, value in vars(mod).items():
            origin = getattr(value, "__module__", None)
            if isinstance(origin, str) and origin.startswith("dhc.tooling"):
                leaks.append((name, attr))
    return leaks


def test_core_does_not_import_tooling():
    _import_all_agent_modules()
    leaks = _tooling_leaks()
    assert not leaks, f"framework core imported tooling: {leaks}"


def test_runtime_constructor_has_no_store_param():
    """The core Runtime is constructible without any store knowledge."""
    import inspect

    from dhc.agent.runtime import Runtime

    params = inspect.signature(Runtime.__init__).parameters
    assert "artifact_store" not in params


def test_agent_has_no_store_param():
    import inspect

    from dhc.agent.agent import Agent

    params = inspect.signature(Agent.__init__).parameters
    assert "artifact_store" not in params


def test_core_owns_the_directed_message_primitive():
    """Decision 0015: ``send`` is a core surface — the base namespace binds
    it (an action, like spawn/complete), not a registered tool."""
    from dhc.agent.agent import Agent
    from dhc.agent.runtime import Runtime

    rt = Runtime()
    agent = Agent(id="a1", requirement="r", runtime=rt)
    ns = rt._build_namespace(agent)
    assert "send" in ns and callable(ns["send"])
    assert hasattr(Runtime, "send")
    # The channel names are NOT core: they come from dhc.tooling.
    for channel_tool in ("room", "messenger", "escalate", "ask_operator", "post", "channel_read"):
        assert channel_tool not in ns
