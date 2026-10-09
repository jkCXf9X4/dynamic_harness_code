"""The framework core must stay store-unaware (decision 0014).

The artifact store is operator tooling (``dhc.tooling``); the framework core
(``dhc.agent``) knows artifacts only as opaque ids on ``Result``/``Completion``
and the ``artifact_published`` event kind. This test locks the dependency
direction: no module under ``dhc.agent`` may import ``dhc.tooling``.
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
