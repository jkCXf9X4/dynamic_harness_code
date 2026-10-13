"""W7.1: the quickstart tutorial executes — the docs test.

``docs/quickstart.md`` is a tutorial, not a claim: this test extracts every
```python code block from it and EXECUTES them in one shared namespace, in
document order. If the tutorial drifts from the code (an API renamed, a
fixture changed, an output line wrong), this test fails — the same contract
``tests/test_integration.py`` puts on the fixture pattern the tutorial
teaches.

Mechanism (deliberate choice): literal extraction + exec, not doctest —
the tutorial's blocks are prose-shaped (they build on each other across
sections, and their printed outputs are illustrative comments), and doctest
would force either fake REPL prompts on every line or brittle expected-
output matching. Executing the blocks as a script is the honest check: the
code runs, in order, against the real wired runtime.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]
QUICKSTART = REPO_ROOT / "docs" / "quickstart.md"

#: ```python fenced blocks (non-greedy, DOTALL across lines).
_PY_BLOCK = re.compile(r"```python\n(.*?)```", re.DOTALL)


def _blocks() -> list[str]:
    """Every python block in the tutorial, in document order."""
    text = QUICKSTART.read_text(encoding="utf-8")
    blocks = _PY_BLOCK.findall(text)
    assert blocks, "docs/quickstart.md contains no python blocks"
    return blocks


def test_quickstart_exists_and_has_blocks():
    """The tutorial exists and carries executable python blocks."""
    assert QUICKSTART.exists()
    assert len(_blocks()) >= 5  # one per section at minimum


def test_quickstart_blocks_execute(tmp_path, capsys):
    """Every python block runs, in order, in one shared namespace.

    The blocks are the tutorial: build_runtime -> spawn -> fan-out ->
    await -> read artifacts -> inspect events -> stop. Executing them
    against the real wired runtime (mock driver, temp artifact root) is
    the drift guard.
    """
    from dhc import build_runtime  # noqa: F401  (imported by the blocks)

    namespace: dict = {"__name__": "quickstart_docs"}
    for i, block in enumerate(_blocks()):
        code = compile(block, f"<quickstart block {i}>", "exec")
        exec(code, namespace)  # noqa: S102 - the point of the test

    # The tutorial's own claims, checked: the root completed with one
    # final artifact, two children settled, the store round-trips.
    completion = namespace["completion"]
    assert completion.status.value == "completed"
    assert completion.summary == "root done"
    assert len(completion.artifact_ids) == 1

    runtime = namespace["runtime"]
    children = runtime.children_of(namespace["root"].id)
    assert len(children) == 2
    states = sorted(
        runtime.await_(cid).status.value for cid in children
    )
    assert states == ["completed", "completed"]

    final_id = completion.artifact_ids[0]
    assert runtime.artifact_store.get_headline(final_id) == "final report"
    assert (
        runtime.artifact_store.get_summary(final_id)
        == "aggregated findings"
    )

    # The boundary log saw the fan-out and every settlement.
    assert len(runtime.boundary_log.read(kind="spawned")) == 2
    assert len(runtime.boundary_log.read(kind="settled")) == 3

    runtime.stop()


def test_quickstart_child_block_publishes_and_completes(tmp_path):
    """The tutorial's CHILD script is a real settle pattern on its own."""
    from dhc import MockDriver, build_runtime

    runtime = build_runtime(mock=True, artifact_root=tmp_path)
    runtime.start()
    child = namespace_child = (
        "art = publish('child finding', 'child summary', 'child report body')\n"
        "result = complete('child done', artifacts=[art.id])"
    )
    agent = runtime.spawn("child work", driver=MockDriver.single(child))
    comp = runtime.await_(agent.id)
    assert comp.status.value == "completed"
    assert comp.summary == "child done"
    assert len(comp.artifact_ids) == 1
    runtime.stop()
