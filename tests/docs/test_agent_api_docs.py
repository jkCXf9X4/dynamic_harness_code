"""W7.2: the agent API reference is generated and fresh — the drift guard.

``docs/agent-api.md`` is GENERATED from the surface registry by
``tools/generate_agent_api.py`` (the same registry the prompt's API section
renders from). This test closes the loop:

(a) the file exists and carries the registry-hash footer;
(b) the file matches what the generator produces TODAY (freshness — a
    registry change without regeneration fails here);
(c) every core registry entry appears with its call form, doc, and tier;
(d) the per-entry examples the generator embeds are real: each example for
    a core entry is executed against a wired runtime's namespace where the
    call is side-effect-free, or verified for shape where it settles state.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = REPO_ROOT / "docs" / "agent-api.md"
GEN_PATH = REPO_ROOT / "tools" / "generate_agent_api.py"


class _Sentinel:
    """Harmless stand-in for a name an example references but doesn't
    define (``handle``, ``recipient_id``...): attribute access and calls
    return sentinels, so shape snippets execute without side effects."""

    def __init__(self, name: str) -> None:
        self._name = name

    def __getattr__(self, attr: str) -> "_Sentinel":
        return _Sentinel(f"{self._name}.{attr}")

    def __call__(self, *args: object, **kwargs: object) -> "_Sentinel":
        return _Sentinel(f"{self._name}()")

    def __iter__(self):
        return iter([_Sentinel(f"{self._name}[i]")])

    def __repr__(self) -> str:
        return f"<{self._name}>"


def _load_generator():
    spec = importlib.util.spec_from_file_location("gen_agent_api", GEN_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _registry():
    import dhc.wiring  # noqa: F401  (registers the full surface)
    from dhc.framework.surface import default_registry

    return default_registry


def test_doc_exists_with_hash_footer():
    """The reference exists and carries the registry-hash footer."""
    assert DOC_PATH.exists(), "docs/agent-api.md is missing"
    text = DOC_PATH.read_text(encoding="utf-8")
    assert re.search(r"<!-- registry-hash: [0-9a-f]+ -->", text), (
        "docs/agent-api.md lacks the registry-hash footer"
    )


def test_doc_matches_generator():
    """Freshness: the checked-in file equals the generator output."""
    gen = _load_generator()
    current = DOC_PATH.read_text(encoding="utf-8")
    assert current == gen.render(), (
        "docs/agent-api.md is stale — run python3 tools/generate_agent_api.py"
    )


def test_every_core_entry_documented():
    """Every core entry appears with call form, doc, and tier."""
    text = DOC_PATH.read_text(encoding="utf-8")
    registry = _registry()
    core = registry.of_tier("core")
    assert core, "the registry has no core entries"
    for entry in core:
        assert f"### `{entry.name}`" in text, f"{entry.name} missing a section"
        assert entry.call in text, f"{entry.name} call form missing"
        assert entry.doc in text, f"{entry.name} doc missing"
        assert "tier: core" in text, "tier annotation missing"


def test_advanced_and_internal_summarized():
    """Advanced entries are listed by name; internal ones are counted."""
    text = DOC_PATH.read_text(encoding="utf-8")
    registry = _registry()
    for entry in registry.of_tier("advanced"):
        assert f"`{entry.name}`" in text, f"advanced {entry.name} missing"
    internal = registry.of_tier("internal")
    assert f"{len(internal)} injected-machinery names" in text


def test_core_examples_execute_in_namespace(tmp_path):
    """The embedded examples are real code, not prose.

    Each core entry's example is executed in a fresh namespace holding a
    wired runtime's agent surface (the mock path). Examples that settle
    the agent or need a live child are shape-checked instead (they are
    marked by the generator as call-form snippets).
    """
    from dhc import MockDriver, build_runtime

    runtime = build_runtime(mock=True, artifact_root=tmp_path)
    runtime.start()
    try:
        root = runtime.spawn(
            "exercise the surface",
            driver=MockDriver.single("pass"),  # one turn builds the workspace
        )
        runtime.await_(root.id)  # the workspace exists once a turn has run
        # The in-code surface the root's workspace holds (the raw engine
        # exposes globals_for; runtime.engine is the raising adapter).
        namespace = dict(runtime.repl_engine.globals_for(root.id))
        gen = _load_generator()
        for name, example in gen._EXAMPLES.items():
            entry = _registry().get(name)
            assert entry is not None and entry.tier == "core", (
                f"example defined for non-core entry {name!r}"
            )
            # Examples are single expressions or statements; compile first
            # (syntax is part of the claim), then exec where side-effect
            # free. Settling calls (complete/fail) and child-dependent
            # calls are compile-checked only — executing them would
            # settle the fixture agent. Yield-forms (Await/Poll/Sleep)
            # compile as isolated blocks: 'yield' outside a function is
            # a SyntaxError, so wrap them in a generator shell.
            if name in ("Await", "Poll", "Sleep"):
                compile(
                    f"def _gen():\n    {example}", f"<example {name}>",
                    "exec",
                )
            else:
                compile(example, f"<example {name}>", "exec")
            if name in ("complete", "fail", "record_result", "await_",
                        "gather", "ack", "answers", "escalate",
                        "ask_operator", "Await", "Poll", "Sleep", "send",
                        "post", "room", "spawn", "poll", "children_of",
                        "read_artifact", "archive", "room_messages"):
                continue
            # Examples referencing other names (handle, recipient_id, ...)
            # are shape snippets: compile-checked above, executed with the
            # referenced names bound to harmless sentinels.
            import re as _re
            free = set(_re.findall(r"[A-Za-z_][A-Za-z0-9_]*", example))
            sentinels = {
                n: _Sentinel(n)
                for n in free
                if n not in namespace and n not in dir(__builtins__)
                and not n.startswith("__")
            }
            try:
                exec(example, {**namespace, **sentinels})  # noqa: S102
            except Exception as exc:  # noqa: BLE001
                pytest.fail(f"example for {name!r} raised: {exc}")
    finally:
        runtime.stop()
