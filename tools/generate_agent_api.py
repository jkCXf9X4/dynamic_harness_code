#!/usr/bin/env python3
"""Generate ``docs/agent-api.md`` from the surface registry (W7.2).

The agent API reference is GENERATED from
:class:`dhc.framework.surface.default_registry` — the same single source of
truth the prompt's API section is rendered from — so the reference cannot
drift from the surface. Every core entry appears with its call form, one-line
doc, tier, and a minimal example; advanced entries are listed by name and
doc; internal entries are counted only.

A freshness test (``tests/docs/test_agent_api_docs.py``) asserts the
checked-in file matches what this script produces (via a registry hash in
the footer), so a registry change without a regeneration fails CI.

Usage::

    python3 tools/generate_agent_api.py            # write in place
    python3 tools/generate_agent_api.py --check    # exit 1 if stale
    python3 tools/generate_agent_api.py --out PATH # write to PATH
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

# Make the package importable when run as a plain script (no install needed).
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

import dhc.wiring  # noqa: E402,F401  (registers the full surface)
from dhc.framework.surface import default_registry  # noqa: E402

OUTPUT_FILENAME = "agent-api.md"

#: One minimal, honest example per core entry. Each is either real code an
#: agent's action block could run (verified by the docs test) or a comment
#: noting the shape. Keys are entry names.
_EXAMPLES: dict[str, str] = {
    "agent": "agent.status()",
    "spawn": "handle = spawn('research the market')",
    "send": "send(recipient_id, 'please proceed')",
    "complete": "complete('done', artifacts=[art.id])",
    "fail": "fail('data source unavailable')",
    "record_result": "record_result('tool returned empty')",
    "status": "status()",
    "result": "result()",
    "tool": "tool(len, [1, 2, 3])",
    "bash": "bash('ls -1')",
    "await_": "comp = await_(handle)",
    "poll": "poll(handle)",
    "children_of": "handles = children_of(handle)",
    "gather": "comps = gather([c1, c2], return_failures=True)",
    "ack": "ack(escalation_id)",
    "answers": "answers(question_id)",
    "list_tools": "list_tools()",
    "publish": "art = publish('headline', 'summary', 'report body')",
    "read_artifact": "read_artifact(artifact_id, level='summary')",
    "archive": "archive(artifact_id)",
    "list_artifacts": "list_artifacts()",
    "room": "snapshot = room('research')",
    "room_messages": "msgs = room_messages('research')",
    "post": "post('research', 'finding posted')",
    "escalate": "escalate('need human decision', 'blocked on approval')",
    "ask_operator": "qid = ask_operator('which source?')",
    "Await": "yield Await(handle)",
    "Poll": "yield Poll(handle)",
    "Sleep": "yield Sleep(1.0)",
}


def registry_hash() -> str:
    """A stable digest of the registry's descriptive content.

    Covers name, call form, doc, and tier of every entry — so any change
    that alters the generated document changes the hash.
    """
    parts = [
        f"{e.name}|{e.call or ''}|{e.doc}|{e.tier}"
        for e in sorted(default_registry.entries(), key=lambda e: e.name)
    ]
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:16]


def render() -> str:
    """The generated API reference (deterministic; sorted by name)."""
    core = default_registry.of_tier("core")
    advanced = default_registry.of_tier("advanced")
    internal = default_registry.of_tier("internal")

    lines: list[str] = []
    lines.append("# Agent API — the in-block surface")
    lines.append("")
    lines.append(
        "<!-- GENERATED FILE — do not edit. Regenerate with "
        "python3 tools/generate_agent_api.py -->"
    )
    lines.append("")
    lines.append(
        "Every name an agent's action block can call, generated from the "
        "surface registry (`src/dhc/framework/surface.py`) — the same "
        "single source of truth the prompt's API section is rendered from. "
        "The registry currently holds "
        f"{len(default_registry)} entries: {len(core)} core, "
        f"{len(advanced)} advanced, {len(internal)} internal."
    )
    lines.append("")
    lines.append(
        "- **core** — prompt-visible and in `list_tools()`: the vocabulary "
        "an agent is taught."
    )
    lines.append(
        "- **advanced** — in `list_tools()` but not prompt-visible: "
        "reachable, not advertised."
    )
    lines.append(
        "- **internal** — never advertised: injected machinery (the "
        "fabrication kit, the driver factory)."
    )
    lines.append("")
    lines.append(
        "A tutorial that runs this surface end to end: "
        "[quickstart.md](quickstart.md)."
    )
    lines.append("")
    lines.append("## Core")
    lines.append("")
    for e in core:
        lines.append(f"### `{e.name}`")
        lines.append("")
        lines.append(f"```python")
        lines.append(f"{e.call}")
        lines.append(f"```")
        lines.append("")
        lines.append(f"{e.doc} *(tier: core)*")
        lines.append("")
        example = _EXAMPLES.get(e.name)
        if example:
            lines.append("Example:")
            lines.append("")
            lines.append("```python")
            lines.append(example)
            lines.append("```")
            lines.append("")
    lines.append("## Advanced")
    lines.append("")
    lines.append("Reachable, not advertised (visible via `list_tools()`):")
    lines.append("")
    for e in advanced:
        lines.append(f"- `{e.name}` — {e.doc}")
    lines.append("")
    lines.append("## Internal")
    lines.append("")
    lines.append(
        f"{len(internal)} injected-machinery names, never advertised: "
        + ", ".join(f"`{e.name}`" for e in internal)
        + "."
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"<!-- registry-hash: {registry_hash()} -->")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 (and print a diff hint) if the file is stale",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="write to PATH instead of docs/agent-api.md",
    )
    args = parser.parse_args(argv)

    text = render()
    out_path = (
        Path(args.out) if args.out else _REPO_ROOT / "docs" / OUTPUT_FILENAME
    )
    if args.check:
        current = (
            out_path.read_text(encoding="utf-8")
            if out_path.exists()
            else ""
        )
        if current != text:
            print(
                f"{out_path} is stale — run python3 tools/generate_agent_api.py",
                file=sys.stderr,
            )
            return 1
        print(f"{out_path} is current")
        return 0

    out_path.write_text(text, encoding="utf-8")
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
