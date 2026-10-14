"""Subagent setup from synthesized run_code / invoke calls — the ergonomics suite.

The literal fan-out idiom (a driver-scripted block writing
``c1 = spawn(...)`` by hand) is pinned by ``test_integration`` and
``examples/_mock_scripts.py``. But agents routinely *compose* the calls
that set up their children instead of writing them literally: a task list
becomes one setup call per entry, a risky setup is probed before it is
trusted, and a helper is invoked rather than inlined. This suite pins
that those synthesized paths are as easy and as well-behaved as the
literal one, on the fully-wired runtime:

* run_code — ``run_block(code, spec)`` executes a synthesized
  ``def call(self, spec)`` snippet against the agent's own persistent
  workspace and INVOKES it with the agent facade as ``self`` — the same
  format and receiver discipline as the delegation snippet below, so one
  shape governs all agent-side code. The format is enforced (a flat
  payload is rejected as a failed ``Result`` naming the required shape),
  and data crosses the boundary only through the snippet contract:
  ``spec`` in, the return value out (``res.value``), and ``state`` for
  persistence. Payload locals stay function-scoped — they never leak
  into the workspace — while module-level names the payload defines
  (``call`` itself, helpers) are ordinary workspace citizens. The
  default runner's driver-produced blocks bypass this entirely (the raw
  ``exec_block``): enforcement is on the run_code surface, not on the
  internal block path.
* invoke — ``agent.tool(callable, ...)`` wraps a setup helper in a
  ``ToolResult`` envelope: a failure inside the helper is a value
  (``ok=False`` + text, INFO-020), not a transport break that kills the
  turn.
* data-driven fan-out — a plain list of requirements becomes a list of
  spawned, joined children with no boilerplate beyond the loop: one
  setup snippet, one run_code call per task with a different ``spec``
  (the call arguments make it data-driven); ``gather`` (W3.8) is the
  join.
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
so the code reads as the agent writes it (indented triple-quoted text would be
an ``IndentationError`` in ``exec`` code; ``textwrap.dedent`` restores
column-0 statements while keeping relative indentation). Snippet payloads
embedded in those blocks use ``'''`` literals — after the outer dedent
they land at column 0 with their relative indentation intact, so a
payload reads as the plain Python it is.
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


# --------------------------------------------------------------------------- #
# run_code: a synthesized snippet sets up the child
# --------------------------------------------------------------------------- #


def test_synthesized_run_code_spawns_and_returns_handle(runtime):
    """One ``run_block`` call carries the whole child setup — requirement
    plus the child's driver script — as a ``def call(self)`` snippet; the
    handle the snippet returns comes back as ``res.value`` (the outbound
    channel of the snippet contract), and the ``call`` entrypoint itself
    persists as a workspace citizen: module-level names the payload
    defines still share the workspace, locals do not."""
    block = textwrap.dedent(
        """
        setup_code = '''
        def call(self):
            h = self.spawn('count stars',
                           driver=MockDriver.single("complete('stars counted')"))
            return h
        '''
        res = run_block(setup_code)
        comp = await_(res.value)
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

    ws = runtime.repl_engine.globals_for(root.id)
    # The outbound channel: the snippet's return value is res.value.
    assert ws["res"].value.id == children[0]
    # Module-level payload names are workspace citizens...
    assert callable(ws["call"])
    # ...but payload locals are function-scoped and never leak.
    assert "h" not in ws


def test_data_driven_fanout_via_synthesized_spawn_calls(runtime):
    """A list of requirements becomes spawned-and-joined children: the
    agent writes ONE setup snippet — the call arguments make it
    data-driven, ``spec`` carrying the requirement and the child's
    script — and synthesizes one run_code call per task with a different
    ``spec``, keeping the returned handles in a list for a single
    ``gather`` join. No boilerplate beyond the loop, and no repr-escaping
    anywhere."""
    block = textwrap.dedent(
        """
        setup_code = '''
        def call(self, spec):
            h = self.spawn(spec['requirement'],
                           driver=MockDriver.single(spec['child']))
            return h
        '''
        tasks = ['alpha', 'beta', 'gamma']
        handles = []
        for task in tasks:
            spec = {'requirement': 'do ' + task,
                    'child': f"complete('done: {task}')"}
            res = run_block(setup_code, spec)
            handles.append(res.value)

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
# run_code: the enforced snippet format
# --------------------------------------------------------------------------- #


def test_run_code_requires_snippet_format(runtime):
    """A flat payload (the pre-format shape) is rejected as a value: the
    Result names the required format, nothing is exec'd (no child, no
    workspace pollution — validation fails before any exec), and the
    parent's turn carries on."""
    block = textwrap.dedent(
        """
        flat = "answer = spawn('flat child')"
        res = run_block(flat)
        state['probe_ok'] = res.ok
        state['probe_reason'] = res.reason
        result = complete('format enforced')
        """
    )
    root = runtime.spawn("parent", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "format enforced"

    ws = runtime.repl_engine.globals_for(root.id)
    assert ws["state"]["probe_ok"] is False
    assert "def call(self, spec)" in ws["state"]["probe_reason"]

    # Nothing ran: no child, and the payload never touched the workspace.
    assert runtime.children_of(root.id) == []
    assert "answer" not in ws


@pytest.mark.parametrize(
    "payload, reason_snippet",
    [
        pytest.param("x = 1", "no module-level 'call'", id="no-call-def"),
        pytest.param(
            "def call(agent):\n    return 1",
            "first parameter 'self'",
            id="wrong-self-name",
        ),
        pytest.param(
            "def call(self, task):\n    return 1",
            "second parameter 'spec'",
            id="wrong-spec-name",
        ),
        pytest.param(
            "def call(self, spec, extra):\n    return 1",
            "at most (self, spec)",
            id="too-many-params",
        ),
        pytest.param(
            "def call(self, *args):\n    return 1",
            "no *args/**kwargs",
            id="varargs",
        ),
        pytest.param(
            "def call(self):\n    return 1\n\n\ndef call(self):\n    return 2",
            "exactly one",
            id="duplicate-call",
        ),
        pytest.param(
            "async def call(self):\n    return 1",
            "plain (sync) function",
            id="async-call",
        ),
        pytest.param("def call(self:\n    return 1", "SyntaxError", id="syntax"),
    ],
)
def test_run_code_rejects_wrong_entrypoint_shapes(runtime, payload, reason_snippet):
    """Each malformed entrypoint shape is rejected as a failed Result
    whose reason names the specific violation — the format is enforced,
    not advisory, and a rejected payload never executes."""
    block = textwrap.dedent(
        f"""
        res = run_block({payload!r})
        state['probe_ok'] = res.ok
        state['probe_reason'] = res.reason
        result = complete('rejected')
        """
    )
    root = runtime.spawn("format guard", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "rejected"

    ws = runtime.repl_engine.globals_for(root.id)
    assert ws["state"]["probe_ok"] is False
    assert reason_snippet in ws["state"]["probe_reason"]
    assert runtime.children_of(root.id) == []


# --------------------------------------------------------------------------- #
# run_code: the snippet sharing contract
# --------------------------------------------------------------------------- #


def test_run_code_sharing_contract_spec_state_and_locals(runtime):
    """The snippet contract's three channels, pinned end to end: ``spec``
    in (the call arguments), the return value out, and ``state`` for
    persistence across successive run_code calls. Locals never leak into
    the workspace; module-level helpers a payload defines are ordinary
    workspace citizens."""
    block = textwrap.dedent(
        """
        first = '''
        def call(self, spec):
            state['mark'] = spec
            local_only = 'never leaks'
            return state['mark']
        '''
        second = '''
        def helper():
            return 'helper ran'

        def call(self):
            return state['mark'] + ' / ' + helper()
        '''
        res1 = run_block(first, 'written by payload one')
        res2 = run_block(second)
        state['saw'] = res2.value
        result = complete('contract pinned')
        """
    )
    root = runtime.spawn("parent", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "contract pinned"

    ws = runtime.repl_engine.globals_for(root.id)
    # spec in, return out.
    assert ws["res1"].value == "written by payload one"
    # state persists across run_code calls (the sanctioned channel).
    assert ws["state"]["mark"] == "written by payload one"
    # A module-level helper defined by a payload is a workspace citizen...
    assert callable(ws["helper"])
    # ...and its output flowed through the second payload's return value.
    assert ws["res2"].value == "written by payload one / helper ran"
    # Payload locals never leak into the workspace.
    assert "local_only" not in ws


def test_run_code_entrypoint_arities_and_none_return(runtime):
    """Both entrypoint shapes work — ``def call(self)`` and ``def
    call(self, spec)`` — and a payload whose entrypoint returns ``None``
    falls back to the raw exec's Result (ok, no value) rather than
    failing."""
    block = textwrap.dedent(
        """
        no_args = '''
        def call(self):
            return 42
        '''
        with_spec = '''
        def call(self, spec):
            return spec * 2
        '''
        returns_none = '''
        def call(self):
            pass
        '''
        state['a'] = run_block(no_args).value
        state['b'] = run_block(with_spec, 21).value
        res = run_block(returns_none)
        state['c'] = {'ok': res.ok, 'value': res.value}
        result = complete('arities ok')
        """
    )
    root = runtime.spawn("parent", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "arities ok"

    ws = runtime.repl_engine.globals_for(root.id)
    assert ws["state"]["a"] == 42
    assert ws["state"]["b"] == 42
    assert ws["state"]["c"] == {"ok": True, "value": None}


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
    """A typo'd setup call (W3.9's ``namespce=``) composed into a run_code
    snippet surfaces as the returned Result's reason when the entrypoint
    is INVOKED — the did-you-mean text survives the composed path — and
    creates no child while the parent's turn carries on."""
    block = textwrap.dedent(
        """
        setup_code = '''
        def call(self):
            h = spawn('typo child', namespce={'x': 1})
        '''
        res = run_block(setup_code)
        state['probe_ok'] = res.ok
        state['probe_reason'] = res.reason
        result = complete('probe survived')
        """
    )
    root = runtime.spawn("parent", driver=MockDriver.single(block))

    comp = root.await_()
    assert comp.status == AgentStatus.completed
    assert comp.summary == "probe survived"

    # The did-you-mean TypeError is visible through the Result envelope.
    ws = runtime.repl_engine.globals_for(root.id)
    assert ws["state"]["probe_ok"] is False
    assert "namespce" in ws["state"]["probe_reason"]
    assert "did you mean 'namespace'" in ws["state"]["probe_reason"]

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
