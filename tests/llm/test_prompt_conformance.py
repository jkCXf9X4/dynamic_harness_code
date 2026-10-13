"""W0.1: prompt↔API conformance — the drift guard (F1).

The wired prompt's API section is GENERATED from the surface registry
(W1.4), and the registry is generated from the registration sites — but
generation alone does not catch a lie in the registry itself. This test
closes the loop in both directions against a freshly-wired namespace:

(a) every callable CLAIMED in the wired prompt's API section exists in
    the namespace with a compatible arity (catches the
    ``escalate(reason)`` vs ``escalate(requirement, reason)`` class of
    bug — a claim the code cannot satisfy);
(b) every core-tier registry entry appears in the prompt (catches a
    registration that forgot to promote its name);
(c) no prompt file shipped in ``src/dhc/llm/`` teaches a callable that
    does not resolve in the wired namespace (catches doctrine drift —
    ``converse``, ``report``, ``plan``, ...).

The parser targets the registry-GENERATED prompt section (the sentence
``Available in the namespace: ...``), not any hand-written literal —
W1.4 deleted the literal, and this test must survive that.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dhc.llm.driver import default_build_prompt  # noqa: E402
from dhc.framework.surface import default_registry  # noqa: E402
from dhc.wiring import build_runtime  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_LLM = REPO_ROOT / "src" / "dhc" / "llm"

#: The sentence the generated API section is rendered into (see
#: ``dhc.framework.surface``). Parsed, not imported, so the test guards
#: the actual prompt bytes.
_API_SENTENCE = re.compile(
    r"Available in the namespace: (.+?)\.(?:\n|$)", re.DOTALL
)

#: One claimed call: ``name(...)`` or ``obj.method(...)``.
_CALL = re.compile(r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\(([^)]*)\)")

#: A bare name claim (no parens), e.g. ``agent``. Skips keywords and
#: default-value literals that appear inside call forms.
_BARE = re.compile(r"(?<![\w.])([A-Za-z_][A-Za-z0-9_]*)(?![\w(])")

#: Tokens that are never surface names (keyword defaults in call forms).
_NOT_NAMES = frozenset({"None", "True", "False", "driver", "on_done"})


def _wired_namespace(tmp_path):
    """A freshly-wired runtime's composed namespace for one agent."""
    rt = build_runtime(mock=True, artifact_root=str(tmp_path))
    try:
        agent = rt.spawn("conformance probe")
        ns = rt._build_namespace(rt.get(agent.id))
        return ns
    finally:
        rt.stop()


def _prompt_api_claims(prompt: str) -> dict[str, str]:
    """Extract ``name -> call form`` claims from the prompt's API section."""
    m = _API_SENTENCE.search(prompt)
    assert m, "prompt has no 'Available in the namespace: ...' API section"
    body = m.group(1)
    claims: dict[str, str] = {}
    # Call-form claims first: ``name(a, b=1)`` / ``obj.method(a)``.
    for match in _CALL.finditer(body):
        claims[match.group(1)] = match.group(2)
    # Bare-name claims (e.g. trailing ``agent``): the sentence with every
    # call form blanked out, so parameter names are never mistaken for
    # surface names.
    stripped = _CALL.sub(" ", body)
    for match in _BARE.finditer(stripped):
        name = match.group(1)
        if name not in claims and "." not in name and name not in _NOT_NAMES:
            claims[name] = ""
    return claims


def _positional_bounds(params: str) -> tuple[int, int] | None:
    """(min, max) positional args a call form accepts, or None if unknowable."""
    if not params.strip():
        return (0, 0)
    min_required = 0
    max_positional = 0
    for raw in params.split(","):
        token = raw.strip()
        if not token:
            continue
        if token.startswith("*"):
            # *args / **kwargs: unbounded.
            if token == "*args":
                max_positional = 10**6
            continue
        default = "=" in token
        if not default:
            min_required += 1
        max_positional += 1
    return (min_required, max_positional)


def _signature_bounds(fn) -> tuple[int, int] | None:
    """(min, max) positional args the callable accepts, or None."""
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return None
    min_required = 0
    max_positional = 0
    for param in sig.parameters.values():
        if param.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            max_positional += 1
            if param.default is inspect.Parameter.empty:
                min_required += 1
        elif param.kind == inspect.Parameter.VAR_POSITIONAL:
            max_positional = 10**6
    return (min_required, max_positional)


def _resolve(ns: dict, name: str):
    """Resolve ``name`` (or ``obj.attr``) in the namespace; None if absent."""
    if "." in name:
        obj_name, _, attr = name.partition(".")
        obj = ns.get(obj_name)
        return getattr(obj, attr, None) if obj is not None else None
    return ns.get(name)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


class _ProbeStatus:
    done = False
    ok = False
    reason = "not settled"


class _ProbeAgent:
    """A minimal agent stand-in for prompt assembly (no runtime needed)."""

    def __init__(self):
        self.requirement = "conformance probe"
        self.acceptance = ("probe done",)

    def status(self):
        return _ProbeStatus()


def _probe_agent() -> _ProbeAgent:
    return _ProbeAgent()


# --------------------------------------------------------------------------- #
# (a) + (b): the wired prompt ↔ the wired namespace
# --------------------------------------------------------------------------- #


def test_prompt_api_claims_resolve_in_wired_namespace(tmp_path):
    """Every callable the prompt claims exists in the wired namespace."""
    ns = _wired_namespace(tmp_path)
    prompt = default_build_prompt(_probe_agent())
    claims = _prompt_api_claims(prompt)
    assert claims, "no API claims parsed from the prompt"
    unresolved = [name for name in claims if _resolve(ns, name) is None]
    assert not unresolved, f"prompt claims unresolvable names: {unresolved}"


def test_prompt_api_claims_match_real_arity(tmp_path):
    """Every claimed call form is aritically satisfiable (the escalate class
    of bug: the prompt teaches N args, the code takes M != N)."""
    ns = _wired_namespace(tmp_path)
    prompt = default_build_prompt(_probe_agent())
    claims = _prompt_api_claims(prompt)
    problems = []
    for name, params in claims.items():
        fn = _resolve(ns, name)
        if fn is None or not callable(fn):
            continue  # existence is the previous test's job
        claimed = _positional_bounds(params)
        actual = _signature_bounds(fn)
        if claimed is None or actual is None:
            continue
        cmin, cmax = claimed
        amin, amax = actual
        # The claim must be callable as written: its required count must
        # fit within the callable's accepted range, and the callable's
        # required count must be coverable by the claim's range.
        if not (cmin <= amax and amin <= cmax):
            problems.append(
                f"{name}: prompt teaches {params!r} (positional "
                f"{cmin}..{cmax}) but the wired callable takes "
                f"{amin}..{amax}"
            )
    assert not problems, "prompt/API arity drift:\n" + "\n".join(problems)


def test_every_core_registry_entry_appears_in_prompt(tmp_path):
    """Reverse direction: every core-tier registry entry is documented."""
    prompt = default_build_prompt(_probe_agent())
    m = _API_SENTENCE.search(prompt)
    assert m
    body = m.group(1)
    missing = [
        e.name
        for e in default_registry.of_tier("core")
        if e.name not in body
    ]
    assert not missing, f"core surface names missing from the prompt: {missing}"


def test_core_claims_are_registry_core(tmp_path):
    """The prompt's API section is exactly the registry's core tier."""
    prompt = default_build_prompt(_probe_agent())
    claims = _prompt_api_claims(prompt)
    core = {e.name for e in default_registry.of_tier("core")}
    # Every core entry's call form names it (``name`` or ``name.attr``).
    claimed_names = {c.split("(")[0].split(".")[0] for c in claims}
    assert claimed_names == core, (
        f"prompt API section != registry core tier:\n"
        f"  only in prompt: {sorted(claimed_names - core)}\n"
        f"  only in registry: {sorted(core - claimed_names)}"
    )


# --------------------------------------------------------------------------- #
# (c): shipped prompt files teach no unresolvable callable
# --------------------------------------------------------------------------- #


def test_shipped_prompt_files_teach_no_unresolvable_callable(tmp_path):
    """No prompt data file in src/dhc/llm/ teaches a callable that does not
    resolve in the wired namespace (catches doctrine drift: converse,
    report, plan, prune, compress, delegate, ...).

    Scans the shipped prompt FILES (``*.txt``) — the prose an LLM reads.
    The ``.py`` prompt-assembly code is covered by the generated-prompt
    tests above; its docstrings legitimately name code identifiers
    (``merge_api_key()``, ``client.generate_code_block()``) that are not
    agent-surface names.
    """
    ns = _wired_namespace(tmp_path)
    drift = []
    prompt_files = sorted(SRC_LLM.glob("*.txt"))
    assert prompt_files, "no prompt files found in src/dhc/llm/"
    for path in prompt_files:
        text = path.read_text(encoding="utf-8")
        # Backticked call teachings: ``name(...)`` — the doctrine's form.
        for match in re.finditer(r"`([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?)\(", text):
            name = match.group(1)
            if _resolve(ns, name) is None:
                drift.append(f"{path.name}: teaches `{name}(...)` — not in the wired namespace")
    assert not drift, "prompt-file drift:\n" + "\n".join(drift)
