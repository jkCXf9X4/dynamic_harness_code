"""The framework core must stay store-unaware and channel-unaware (0014/0015)
and the repo layout must keep the framework/composition split concrete (0016).

The artifact store and the communication channels are composed tooling
(``dhc.tooling``); the framework core (``dhc.framework``) knows artifacts only
as opaque ids on ``Result``/``Completion`` and the ``artifact_published``
event kind, and knows communication only as the directed-message primitive
(``Runtime.send`` / ``Agent.send``) and the ``message_sent`` event kind.

This test locks the dependency directions and the folder hierarchy itself:

* no module under ``dhc.framework`` may import ``dhc.tooling``, ``dhc.ui``,
  or ``dhc.llm`` (the composition root, ``dhc.wiring``, is the only
  meeting point; the framework imports only ``data`` + ``errors``);
* the framework package ships ZERO tools — no ``*tools*`` module may appear
  under ``dhc/framework/``; every REPL tool home lives in ``dhc.tooling``;
* the framework owns the PUMP, not the loop (0017): ``pump.py`` is the
  machinery; the default agent — the fabrication kit a workspace is born
  with — lives in ``dhc.tooling.fabrication`` and is handed in via
  ``Runtime(kit_factory=...)``;
* the operator's files (review state, resumability) live in ``dhc.ui``.
"""

import importlib
import pkgutil
import sys
from pathlib import Path

import dhc.framework
import dhc.tooling  # noqa: F401 - ensures the package imports cleanly
import dhc.ui  # noqa: F401 - ensures the package imports cleanly


def _import_all_framework_modules() -> None:
    """Import every module under ``dhc.framework`` (walk includes submodules)."""
    for mod in pkgutil.walk_packages(dhc.framework.__path__, prefix="dhc.framework."):
        importlib.import_module(mod.name)


def _leaks_from(*package_prefixes: str) -> list[tuple[str, str]]:
    """(module, attribute) pairs where a dhc.framework module holds a value
    whose defining module lives under one of *package_prefixes*."""
    leaks: list[tuple[str, str]] = []
    for name, mod in sys.modules.items():
        if not name.startswith("dhc.framework"):
            continue
        for attr, value in vars(mod).items():
            origin = getattr(value, "__module__", None)
            if isinstance(origin, str) and origin.startswith(package_prefixes):
                leaks.append((name, attr))
    return leaks


def test_core_does_not_import_tooling():
    _import_all_framework_modules()
    leaks = _leaks_from("dhc.tooling")
    assert not leaks, f"framework core imported tooling: {leaks}"


def test_core_does_not_import_ui():
    _import_all_framework_modules()
    leaks = _leaks_from("dhc.ui")
    assert not leaks, f"framework core imported the operator surface: {leaks}"


def test_core_does_not_import_llm():
    """Decision 0017: the framework never imports the provider plumbing —
    the default agent that wraps a driver is composition, not core."""
    _import_all_framework_modules()
    leaks = _leaks_from("dhc.llm")
    assert not leaks, f"framework core imported provider plumbing: {leaks}"


def test_framework_package_ships_zero_tools():
    """Decision 0016: the framework package contains no tools modules —
    everything installed into agent REPL namespaces lives in dhc.tooling."""
    pkg_dir = Path(dhc.framework.__file__).parent
    py_files = {p.name for p in pkg_dir.glob("*.py")}
    tool_files = sorted(name for name in py_files if "tool" in name)
    assert not tool_files, f"tools found inside the framework package: {tool_files}"

    # ...and the composed side owns the tool homes:
    tooling_dir = Path(dhc.tooling.__file__).parent
    for expected in (
        "framework_tools.py",
        "channel_tools.py",
        "artifact_tools.py",
    ):
        assert (tooling_dir / expected).exists(), f"missing tool home: {expected}"


def test_framework_owns_the_pump_not_the_loop():
    """Decision 0017: the machinery is ``pump.py`` (renamed from loop.py —
    the framework drives agent-authored loops, it does not author them);
    the default agent (the fabrication kit) lives in tooling."""
    framework_dir = Path(dhc.framework.__file__).parent
    assert (framework_dir / "pump.py").exists()
    assert not (framework_dir / "loop.py").exists()

    tooling_dir = Path(dhc.tooling.__file__).parent
    assert (tooling_dir / "fabrication.py").exists(), (
        "the default agent (fabrication kit) must live in dhc.tooling"
    )


def test_pump_without_kit_factory_settles_failed():
    """Decision 0017, the seam's failure mode: a pumpable runtime with no
    composed default agent cannot birth a workspace and settles failed
    with a clear reason (containment, not a crash)."""
    from dhc.framework.repl import ReplEngine
    from dhc.framework.runtime import Runtime
    from dhc.data.models import AgentStatus

    rt = Runtime(engine=ReplEngine())
    assert rt.kit_factory is None
    assert rt._supports_pump() is True
    try:
        handle = rt.spawn("do something")
        completion = handle.await_()
        assert completion.status is AgentStatus.failed
        assert "no fabrication composed" in (completion.reason or "")
    finally:
        rt.stop()


def test_composition_root_hands_in_the_default_agent(tmp_path):
    """Decision 0017: build_runtime composes the default agent — the
    runtime it builds carries the fabrication kit factory from tooling."""
    from dhc.wiring import build_runtime

    rt = build_runtime(mock=True, artifact_root=tmp_path)
    try:
        assert rt.kit_factory is not None
        assert rt.kit_factory.__module__ == "dhc.tooling.fabrication"
    finally:
        rt.stop()


def test_operator_files_live_on_the_operator_side():
    """Decision 0016: the operator's review files (state) and resumability
    (checkpoint) live in dhc.ui — not in the framework, not in tooling."""
    ui_dir = Path(dhc.ui.__file__).parent
    assert (ui_dir / "state.py").exists()
    assert (ui_dir / "checkpoint.py").exists()
    framework_dir = Path(dhc.framework.__file__).parent
    assert not (framework_dir / "state.py").exists()
    assert not (framework_dir / "checkpoint.py").exists()


def test_runtime_constructor_has_no_store_param():
    """The core Runtime is constructible without any store knowledge."""
    import inspect

    from dhc.framework.runtime import Runtime

    params = inspect.signature(Runtime.__init__).parameters
    assert "artifact_store" not in params


def test_agent_has_no_store_param():
    import inspect

    from dhc.framework.agent import Agent

    params = inspect.signature(Agent.__init__).parameters
    assert "artifact_store" not in params


def test_core_owns_the_directed_message_primitive():
    """Decision 0015: ``send`` is a core surface — the base namespace binds
    it (an action, like spawn/complete), not a registered tool."""
    from dhc.framework.agent import Agent
    from dhc.framework.runtime import Runtime

    rt = Runtime()
    agent = Agent(id="a1", requirement="r", runtime=rt)
    ns = rt._build_namespace(agent)
    assert "send" in ns and callable(ns["send"])
    assert hasattr(Runtime, "send")
    # The channel names are NOT core: they come from dhc.tooling.
    for channel_tool in ("room", "messenger", "escalate", "ask_operator", "post", "channel_read"):
        assert channel_tool not in ns
