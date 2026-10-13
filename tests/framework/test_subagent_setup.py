"""Subagent setup from synthesized run_code / invoke calls — the ergonomics suite.

The literal fan-out idiom (a driver-scripted block writing
``c1 = spawn(...)`` by hand) is pinned by ``test_integration`` and
``examples/_mock_scripts.py``. But agents routinely *compose* the calls
that set up their children instead of writing them literally: a task list
becomes one spawn call per entry, a risky setup is probed before it is
trusted, and a helper is invoked rather than inlined. This suite pins
that those synthesized paths are as easy and as well-behaved as the
literal one, on the fully-wired runtime:

* run_code — ``run_block(code)`` executes a synthesized string against
  the agent's own persistent workspace, so names the synthesized code
  defines (the child handle) are workspace citizens the joining code
  reads back (the nested exec and the outer block share one workspace).
* invoke — ``agent.tool(callable, ...)`` wraps a setup helper in a
  ``ToolResult`` envelope: a failure inside the helper is a value
  (``ok=False`` + text, INFO-020), not a transport break that kills the
  turn.
* data-driven fan-out — a plain list of requirements becomes a list of
  spawned, joined children with no boilerplate beyond the loop — the
  agent synthesizes one setup call per task with an ordinary f-string;
  ``gather`` (W3.8) is the join.
* the delegation snippet — the composed form that stays readable at any
  recursion depth: the parent authors the child's behavior as a REAL
  function (``def call(self, spec)`` — receiver and call arguments
  explicit, no repr-escaped script inside a script) and injects it
  through the existing ``namespace=`` seam; the only synthesized string
  is the fixed invocation ``call(agent, spec)``. ``self`` is the child's
  facade, so ``self.spawn``/``self.complete`` attribute to the child.
* failure probing — a typo'd synthesized spawn (W3.9's ``namespce=``)
  surfaces its did-you-mean ``TypeError`` through the returned
  ``Result``/``ToolResult``, creates no child, and leaves the parent's
  turn alive: probe, don't crash (INFO-005 containment, agent-side).

The blocking join (``await_`` / ``gather``) is the in-block idiom. The
``yield Await(handle)`` form taught by the API docs is for agent-authored
``__runner`` sources — a plain block cannot yield: top-level ``yield`` in
``exec`` code is a ``SyntaxError``.

Driver scripts in this file are written as dedented triple-quoted blocks
so the code reads as the agent writes it (indented triple-quoted text
would be an ``IndentationError`` in ``exec`` code; ``textwrap.dedent``
restores column-0 statements while keeping relative indentation).
"""

from __future__ import annotations

import textwrap

import pytest

from dhc.data.models import AgentStatus
from dhc.llm.driver import MockDriver
from dhc.wiring import build_runtime


@pytest.fixture()
def runtime(tmp_path):
    """A fully-wired runtime over a fresh temp artifact root."""
    rt = build_runtime(mock=True, artifact_root=tmp_path)
    rt.start()
    yield rt
    rt.stop()


def _spawn_call(requirement: str, child_block: str, target: str = "h") -> str:
    """The synthesized one-line subagent setup call (the run_code payload).

    The child's driver script is inlined via ``repr()`` so the synthesized
    string is self-contained — the same trick ``examples/_mock_scripts.py``
    uses for literal blocks.
    """
    return (
        f"{target} = spawn({requirement!r}, "
        f"driver=MockDriver.single({child_block!r}))"
    )


# --------------------------------------------------------------------------- #
# run_code: a synthesized string sets up the child
# --------------------------------------------------------------------------- #


def test_synthesized_run_code_spawns_and_handle_persists(runtime):
    """One ``run_block`` call carries the whole child setup — requirement
    plus the child's driver script — and the handle the nested exec
    assigns is a workspace citizen the joining code reads back."""
    setup = _spawn_call("count stars", "complete('stars counted')")
    block = textwrap.dedent(
        f"""
        setup_code = {setup!r}
        run_block(setup_code)
        comp = await_(h)
        result = complete('child said: ' + comp.summary)
        """
    )
    root = runtime.spawn("parent", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "child said: stars counted"

    # The child exists, is parented, and settled.
    children = runtime.children_of(root.id)
    assert len(children) == 1
    child_comp = runtime.await_(children[0])
    assert child_comp.status == AgentStatus.completed
    assert child_comp.summary == "stars counted"

    # The nested exec's assignment persisted in the parent's workspace:
    # the joining code and the synthesized code share one workspace.
    ws = runtime.repl_engine.globals_for(root.id)
    assert "h" in ws
    assert ws["h"].id == children[0]


def test_data_driven_fanout_via_synthesized_spawn_calls(runtime):
    """A list of requirements becomes spawned-and-joined children: the
    agent synthesizes one setup call per task with an ordinary f-string,
    keeps the handles in a list, and joins with ``gather`` — no
    boilerplate beyond the loop, and no repr-escaping anywhere."""
    block = textwrap.dedent(
        """
        tasks = ['alpha', 'beta', 'gamma']
        handles = []
        for task in tasks:
            child = f"complete('done: {task}')"
            req = 'do ' + task
            code = f'h = spawn({req!r}, driver=MockDriver.single({child!r}))'
            run_block(code)
            handles.append(h)

        comps = gather(handles)
        result = complete('%d of %d children completed'
                          % (len(comps), len(handles)))
        """
    )
    root = runtime.spawn("fan out", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "3 of 3 children completed"

    # Every task became exactly one settled child, joined in order.
    children = runtime.children_of(root.id)
    assert len(children) == 3
    for cid in children:
        assert runtime.await_(cid).status == AgentStatus.completed
    ws = runtime.repl_engine.globals_for(root.id)
    assert [c.summary for c in ws["comps"]] == [
        "done: alpha",
        "done: beta",
        "done: gamma",
    ]


# --------------------------------------------------------------------------- #
# The delegation snippet: def call(self, ...) injected via namespace=
# --------------------------------------------------------------------------- #


def test_injected_snippet_sets_up_child_with_explicit_receiver(runtime):
    """The delegation-snippet idiom: the parent authors the child's
    behavior as a real function — ``def call(self, spec)`` — with the
    receiver and the call arguments explicit, and injects it through the
    existing ``namespace=`` seam. The only synthesized string is the
    fixed invocation ``call(agent, spec)``; the child's body is plain
    Python, so deep delegation does not compound repr-escaping (the
    script-inside-script form ``_mock_scripts.py`` uses works, but gets
    crude one level down).

    The receiver is load-bearing: ``self`` is the CHILD's facade, so
    ``self.spawn`` parents the grandchild to the child and
    ``self.complete`` settles the child. The ``Agent`` annotation is
    legal in blocks — ``repl.py`` compiles under
    ``from __future__ import annotations`` and ``exec`` inherits the
    calling frame's future flags, so the annotation is stored as the
    string ``'Agent'`` and never evaluated."""
    block = textwrap.dedent(
        """
        def call(self: Agent, spec):
            g = self.spawn(spec['subtask'],
                           driver=MockDriver.single("complete('grandchild done')"))
            comp = self.await_(g)
            self.complete(spec['headline'] + comp.summary)

        spec = {'subtask': 'grandchild task', 'headline': 'child saw: '}
        c = spawn('child task',
                  driver=MockDriver.single('call(agent, spec)'),
                  namespace={'call': call, 'spec': spec})
        comp = await_(c)
        result = complete('root saw: ' + comp.summary)
        """
    )
    root = runtime.spawn("parent", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "root saw: child saw: grandchild done"

    children = runtime.children_of(root.id)
    assert len(children) == 1
    # self.spawn parented the grandchild to the CHILD, not the root —
    # the explicit receiver is what keeps the tree attribution right.
    grandchildren = runtime.children_of(children[0])
    assert len(grandchildren) == 1
    assert runtime.await_(grandchildren[0]).summary == "grandchild done"


def test_snippet_bare_names_act_on_the_parent_not_the_child(runtime):
    """The one discipline the explicit receiver buys: a snippet's
    ``__globals__`` are the PARENT's workspace (it was defined there), so
    bare names act on the parent — only ``self.*`` acts on the child. A
    snippet that writes bare ``state`` and calls bare ``complete`` bleeds
    both to the parent: the write lands in the parent's state dict and
    the child settles failed with no result of its own. Pinned so the
    idiom's single rule stays loud."""
    block = textwrap.dedent(
        """
        def call(self):
            state['writer'] = self.id
            complete('bare complete settles no child')

        c = spawn('child', driver=MockDriver.single('call(agent)'),
                  namespace={'call': call})
        comp = await_(c)
        state['child_status'] = comp.status.value
        state['child_reason'] = comp.reason
        result = complete('parent ok')
        """
    )
    root = runtime.spawn("parent", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "parent ok"

    children = runtime.children_of(root.id)
    assert len(children) == 1

    # The bare complete() never settled the child: it set the PARENT's
    # last result (later overwritten by the parent's own complete). The
    # child's settle found no result of its own.
    child_comp = runtime.await_(children[0])
    assert child_comp.status == AgentStatus.failed
    assert child_comp.reason == "no result"

    # The bare state write bled to the PARENT's state, carrying the
    # child's id; the child's own state never saw it.
    ws = runtime.repl_engine.globals_for(root.id)
    assert ws["state"]["writer"] == children[0]
    assert ws["state"]["child_status"] == "failed"
    child_ws = runtime.repl_engine.globals_for(children[0])
    assert "writer" not in child_ws["state"]


# --------------------------------------------------------------------------- #
# invoke: a helper sets up the child, wrapped in a ToolResult
# --------------------------------------------------------------------------- #


def test_invoke_setup_helper_through_agent_tool(runtime):
    """``agent.tool`` wraps a setup helper: the child is spawned as a side
    effect, the ToolResult carries the child's id as its text, and the
    parent joins through the handle the helper stashed in state."""
    block = textwrap.dedent(
        """
        def setup():
            h = spawn('scan logs',
                      driver=MockDriver.single("complete('scan done')"))
            state['child'] = h
            return h.id

        tr = agent.tool(setup)
        state['probe'] = {'ok': tr.ok, 'text': tr.text}
        comp = await_(state['child'])
        result = complete('invoked child: ' + comp.summary)
        """
    )
    root = runtime.spawn("parent", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "invoked child: scan done"

    children = runtime.children_of(root.id)
    assert len(children) == 1

    # The ToolResult envelope: ok=True and the child's id as text.
    ws = runtime.repl_engine.globals_for(root.id)
    assert ws["state"]["probe"]["ok"] is True
    assert ws["state"]["probe"]["text"] == children[0]


# --------------------------------------------------------------------------- #
# Failure probing: a bad synthesized setup is a value, not a crash
# --------------------------------------------------------------------------- #


def test_typoed_synthesized_spawn_surfaces_in_result_and_spawns_nothing(
    runtime,
):
    """A typo'd setup call (W3.9's ``namespce=``) composed into a
    ``run_block`` probe surfaces as the returned Result's reason — the
    did-you-mean text survives the composed path — and creates no child
    while the parent's turn carries on."""
    block = textwrap.dedent(
        """
        res = run_block("h = spawn('typo child', namespce={'x': 1})")
        state['probe'] = {'ok': res.ok, 'reason': res.reason}
        result = complete('probe survived')
        """
    )
    root = runtime.spawn("parent", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "probe survived"

    # The did-you-mean TypeError is visible through the Result envelope.
    ws = runtime.repl_engine.globals_for(root.id)
    probe = ws["state"]["probe"]
    assert probe["ok"] is False
    assert "namespce" in probe["reason"]
    assert "did you mean 'namespace'" in probe["reason"]

    # Nothing was created by the failed setup call.
    assert runtime.children_of(root.id) == []


def test_typoed_invoke_captured_in_toolresult_and_spawns_nothing(runtime):
    """The same typo through the invoke path: ``agent.tool`` captures the
    ``TypeError`` as ``ok=False`` with the error text (a tool failure is a
    value, INFO-020) — no child, and the turn survives to completion."""
    block = textwrap.dedent(
        """
        tr = agent.tool(lambda: spawn('typo child', namespce={'x': 1}))
        state['tool_probe'] = {'ok': tr.ok, 'text': tr.text}
        result = complete('tool probe survived')
        """
    )
    root = runtime.spawn("parent", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "tool probe survived"

    ws = runtime.repl_engine.globals_for(root.id)
    tool_probe = ws["state"]["tool_probe"]
    assert tool_probe["ok"] is False
    assert "namespce" in tool_probe["text"]
    assert "did you mean 'namespace'" in tool_probe["text"]

    assert runtime.children_of(root.id) == []
