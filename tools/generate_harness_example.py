#!/usr/bin/env python3
"""Generate ``harness.json.example`` from the canonical :class:`HarnessConfig`.

W5.3: the example file is GENERATED from ``HarnessConfig.model_fields`` (via a
default instance's ``model_dump``), not hand-maintained. Every field of every
section appears with its default value, so the file can never drift from the
model. A freshness test (``tests/data/test_config.py::TestExampleFile``)
asserts the checked-in file matches what this script produces.

Usage::

    python3 tools/generate_harness_example.py            # write in place
    python3 tools/generate_harness_example.py --check    # exit 1 if stale
    python3 tools/generate_harness_example.py --out PATH # write to PATH
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the package importable when run as a plain script (no install needed).
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from dhc.data.config import HarnessConfig  # noqa: E402

EXAMPLE_FILENAME = "harness.json.example"


def render_example() -> str:
    """The example file content: a default HarnessConfig, dumped as JSON.

    A default instance carries every field (with its default value), so the
    dump is a complete, model-derived example. ``indent=2`` + a trailing
    newline keep it diff-friendly.
    """
    data = HarnessConfig().model_dump()
    return json.dumps(data, indent=2) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="exit 1 if the checked-in example file is stale (CI mode)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"output path (default: repo-root {EXAMPLE_FILENAME})",
    )
    args = parser.parse_args(argv)

    out_path = args.out or (_REPO_ROOT / EXAMPLE_FILENAME)
    rendered = render_example()

    if args.check:
        if out_path.exists() and out_path.read_text() == rendered:
            print(f"OK: {out_path} is up to date")
            return 0
        print(f"STALE: {out_path} does not match the generated example")
        return 1

    out_path.write_text(rendered)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
