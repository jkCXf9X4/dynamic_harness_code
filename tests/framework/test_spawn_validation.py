"""W3.9 — agent-facing ``spawn`` kwargs validation.

A misspelled keyword pass-through (e.g. ``namespce=``) must fail loudly with
a ``TypeError`` that names the offending key and offers a did-you-mean
suggestion, instead of being swallowed or surfacing as a bare
``Runtime.spawn() got an unexpected keyword argument`` from the runtime.

The single choke point is :meth:`dhc.framework.agent.Agent.spawn` — both the
raw ``Agent`` and the ``WorkspaceAgent`` facade flow through it (the facade
delegates ``**kwargs`` straight down). ``driver`` and ``namespace`` remain the
only accepted pass-throughs; ``on_done`` is an explicit parameter.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc.data.models import AgentStatus  # noqa: E402
from dhc.framework.agent import Agent, AgentHandle, WorkspaceAgent  # noqa: E402
from dhc.framework.runtime import Runtime  # noqa: E402
from dhc.llm.driver import MockDriver  # noqa: E402


def _bare() -> Runtime:
    rt = Runtime()
    rt.start()
    return rt


def _parent_agent(rt: Runtime) -> Agent:
    """A raw parent Agent attached to *rt* (the object whose ``spawn`` we
    exercise — the choke point both facades flow through)."""
    handle = rt.spawn("parent", driver=MockDriver([]))
    return rt.get(handle.id)


# --------------------------------------------------------------------------- #
# Unknown kwargs fail loudly with a did-you-mean
# --------------------------------------------------------------------------- #


def test_spawn_typo_namespace_suggests_close_match():
    """``namespce=`` is a one-letter typo of ``namespace`` — the message must
    name the offending key AND suggest the close match."""
    rt = _bare()
    try:
        agent = _parent_agent(rt)
        try:
            agent.spawn("task", namespce={"x": 1})
        except TypeError as exc:
            msg = str(exc)
            assert "namespce" in msg
            assert "did you mean 'namespace'" in msg
        else:
            raise AssertionError("spawn() with a typo'd kwarg did not raise")
    finally:
        rt.stop()


def test_spawn_unknown_kwarg_no_close_match_names_key():
    """``driverz=`` has no close match — still a ``TypeError`` that names the
    offending key (and lists the accepted pass-throughs)."""
    rt = _bare()
    try:
        agent = _parent_agent(rt)
        try:
            agent.spawn("task", driverz=1)
        except TypeError as exc:
            msg = str(exc)
            assert "driverz" in msg
        else:
            raise AssertionError("spawn() with an unknown kwarg did not raise")
    finally:
        rt.stop()


def test_spawn_internal_kwarg_rejected():
    """``parent_id`` is framework-internal (set by Agent.spawn itself), not an
    agent-facing pass-through — a caller passing it gets the same loud
    ``TypeError``."""
    rt = _bare()
    try:
        agent = _parent_agent(rt)
        try:
            agent.spawn("task", parent_id="a999")
        except TypeError as exc:
            assert "parent_id" in str(exc)
        else:
            raise AssertionError("spawn() with an internal kwarg did not raise")
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# Allowed pass-throughs keep working
# --------------------------------------------------------------------------- #


def test_spawn_driver_passthrough_still_works():
    """``driver=`` is an accepted pass-through — the child completes."""
    rt = _bare()
    try:
        agent = _parent_agent(rt)
        child = agent.spawn("task", driver=MockDriver.single("complete('ok')"))
        assert isinstance(child, AgentHandle)
        completion = child.await_()
        assert completion.status == AgentStatus.completed
    finally:
        rt.stop()


def test_spawn_namespace_passthrough_still_works():
    """``namespace=`` is an accepted pass-through (the imp001 pattern) — the
    injected name reaches the child's turn namespace."""
    rt = _bare()
    try:
        agent = _parent_agent(rt)
        child = agent.spawn(
            "task",
            driver=MockDriver.single("complete(str(k))"),
            namespace={"k": "v"},
        )
        completion = child.await_()
        assert completion.status == AgentStatus.completed
        # The injected name was visible in the child's turn namespace.
        assert completion.summary == "v"
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# The facade flows through the same choke point
# --------------------------------------------------------------------------- #


def test_workspace_agent_facade_validates_too():
    """The ``WorkspaceAgent`` facade delegates ``**kwargs`` to
    ``Agent.spawn`` — a typo'd kwarg through the facade raises the same
    did-you-mean ``TypeError``."""
    rt = _bare()
    try:
        handle = rt.spawn("parent", driver=MockDriver([]))
        agent = rt.get(handle.id)
        facade = WorkspaceAgent(agent)
        try:
            facade.spawn("task", namespce={"x": 1})
        except TypeError as exc:
            msg = str(exc)
            assert "namespce" in msg
            assert "did you mean 'namespace'" in msg
        else:
            raise AssertionError("facade spawn() with a typo'd kwarg did not raise")
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# Host-side Runtime.spawn is unaffected (pre-existing native behavior)
# --------------------------------------------------------------------------- #


def test_host_side_runtime_spawn_native_typeerror():
    """``Runtime.spawn`` has explicit params and no ``**kwargs`` — an unknown
    kwarg there raises Python's *native* ``TypeError`` (pre-existing, not
    W3.9's concern). Pin that it still raises, and that the message is the
    native one (no did-you-mean), so the two surfaces stay distinguishable."""
    rt = _bare()
    try:
        try:
            rt.spawn("r", bogus=1)
        except TypeError as exc:
            msg = str(exc)
            assert "bogus" in msg
            assert "did you mean" not in msg
        else:
            raise AssertionError("Runtime.spawn() with an unknown kwarg did not raise")
    finally:
        rt.stop()
