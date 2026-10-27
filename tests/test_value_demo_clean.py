"""W0.3 — machine-specificity guard for the flagship demo (F5).

``examples/value_demo.py`` must run green from a **clean checkout** on any
machine — no ``/home/eriro`` path, no editable install, no author-specific
cwd. This test:

1. copies the working tree (excluding caches / venv / git) into a temp dir —
   a stand-in for a clean clone (the changes under test are uncommitted, so a
   working-tree copy is the faithful source, not ``git archive HEAD``);
2. runs ``examples/value_demo.py`` as a subprocess with ``cwd`` set to a
   *different* temp dir and a scrubbed environment (no ``OPENAI_API_KEY``,
   no ``PYTHONPATH`` pointing at the real repo) — so it cannot lean on the
   author's machine;
3. asserts exit code 0.

Before the W2.1 fix this test FAILED: the demo hardcoded
``REPORT_PATH = Path("/home/eriro/pwa/2_work/...")`` (and put the repo root,
not ``src/``, on ``sys.path``), so on a machine without that path / without an
editable install it crashed. After the fix the report lands in a fresh per-run
temp artifact root and the demo is self-contained.

A second test asserts no file under ``examples/`` contains the string
``/home/eriro`` — the machine-specificity tripwire.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

REPO_ROOT = Path(__file__).resolve().parent.parent

# Directories that are caches / environment, not part of a clean checkout.
_EXCLUDE_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".dynamic-harness",
    ".dhc",
    ".pytest_cache",
    ".agents",
}


def _clean_copy(dest: Path) -> None:
    """Copy the working tree into *dest*, skipping caches and the venv."""
    def _ignore(_dir: str, names: list[str]) -> list[str]:
        return [n for n in names if n in _EXCLUDE_DIRS]

    shutil.copytree(REPO_ROOT, dest, ignore=_ignore, symlinks=True)


def _scrubbed_env() -> dict[str, str]:
    """An environment that cannot lean on the author's machine."""
    env = dict(os.environ)
    for key in (
        "OPENAI_API_KEY",
        "OPENROUTER_API_KEY",
        "PYTHONPATH",
        "DHC_WORKSPACE_ROOT",
        "DHC_ARTIFACT_ROOT",
        "DHC_OPENAI_MODEL",
        "DHC_LLM_TIMEOUT_SECONDS",
    ):
        env.pop(key, None)
    return env


def test_value_demo_runs_from_clean_checkout(tmp_path):
    """The demo exits 0 from a clean copy, run from a foreign cwd."""
    clean = tmp_path / "clean_checkout"
    _clean_copy(clean)

    # Run from a DIFFERENT temp dir so the demo cannot rely on the repo cwd.
    run_cwd = tmp_path / "elsewhere"
    run_cwd.mkdir()

    demo = clean / "examples" / "value_demo.py"
    assert demo.exists(), "clean copy is missing examples/value_demo.py"

    proc = subprocess.run(
        [sys.executable, str(demo)],
        cwd=str(run_cwd),
        env=_scrubbed_env(),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, (
        "value_demo.py did not exit 0 from a clean checkout "
        f"(rc={proc.returncode}):\n--- stdout ---\n{proc.stdout}\n"
        f"--- stderr ---\n{proc.stderr}"
    )
    # The report must have been written somewhere (a fresh temp artifact root).
    assert "value report written to" in proc.stdout


def test_no_machine_specific_paths_in_examples():
    """No file under examples/ may contain the author's home path."""
    examples = REPO_ROOT / "examples"
    offenders = []
    for path in examples.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "/home/eriro" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == [], (
        "machine-specific /home/eriro path found in examples/: "
        + ", ".join(offenders)
    )
