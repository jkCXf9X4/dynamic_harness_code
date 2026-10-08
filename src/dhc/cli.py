"""Minimal chat-only TUI for dhc (INFO-028).

The CLI is deliberately thin: it wires the :class:`~dhc.operator.Operator`
and :class:`~dhc.operator.ChatSession` to two persistent files — a context
file holding the current requirement/context and a transcript file holding
the conversation — and renders a banner plus the streamed responses. All chat
semantics live in ``dhc.operator``.

The CLI works without an API key: when ``--mock`` is passed (or no
``OPENAI_API_KEY`` is configured) the deterministic default driver is used,
so every requirement settles with a coded ``complete(requirement)`` action.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Optional, Sequence

from .data.config import get_settings
from .ui.operator import ChatSession, Operator
from .agent.runtime import Runtime


def _default_context_file() -> Path:
    """Return the default context file under the workspace root."""
    settings = get_settings()
    return Path(settings.workspace_root) / ".dhc" / "context.md"


def _default_transcript_file() -> Path:
    """Return the default transcript file under the workspace root."""
    settings = get_settings()
    return Path(settings.workspace_root) / ".dhc" / "transcript.md"


def _ensure_file(path: Path) -> None:
    """Create *path* (and parents) if missing; never overwrite existing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")


def _append(path: Path, text: str) -> None:
    """Append *text* to *path*, creating it if needed."""
    _ensure_file(path)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(text)


def _banner(stream: object, mock: bool, model: str) -> None:
    """Print the startup banner to *stream* (rich when available)."""
    mode = "mock" if mock else f"model={model}"
    try:
        from rich.console import Console

        console = Console(file=stream)
        console.rule("[bold cyan]dhc[/bold cyan]")
        console.print(f"[dim]operator door open — {mode} — type !quit to exit[/dim]")
    except Exception:  # noqa: BLE001 - rich is optional for the banner
        stream.write("dhc — operator door open\n")
        stream.write(f"mode: {mode} — type !quit to exit\n")
        stream.flush()


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser (exposed for tests)."""
    parser = argparse.ArgumentParser(
        prog="dhc",
        description="Minimal chat-only TUI for the dhc agent runtime (INFO-028).",
    )
    parser.add_argument(
        "--context",
        type=Path,
        default=None,
        help="context file holding the current requirement (default: .dhc/context.md)",
    )
    parser.add_argument(
        "--transcript",
        type=Path,
        default=None,
        help="transcript file receiving the conversation (default: .dhc/transcript.md)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="use the deterministic mock driver (no API key needed)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="LLM model name (used by the real driver; ignored in mock mode)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        help="LLM call timeout in seconds (used by the real driver)",
    )
    parser.add_argument(
        "--inspect",
        default=None,
        help="print a read-only workspace view for AGENT_ID and exit",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """The ``dhc`` console entry point.

    Returns 0 on a clean ``!quit`` exit, 1 on error.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    context_file = args.context if args.context is not None else _default_context_file()
    transcript_file = (
        args.transcript if args.transcript is not None else _default_transcript_file()
    )
    _ensure_file(context_file)
    _ensure_file(transcript_file)

    settings = get_settings()
    has_key = bool(settings.openai_api_key or os.environ.get("OPENAI_API_KEY"))
    mock = args.mock or not has_key
    model = args.model or settings.openai_model

    _banner(sys.stdout, mock, model)

    runtime = Runtime(settings=settings)
    runtime.start()
    try:
        operator = Operator(runtime=runtime, stream=sys.stdout)
        if args.inspect is not None:
            view = operator.inspect(args.inspect)
            print(f"inspect {args.inspect}")
            print(f"  status: {view.get('status')}")
            print(f"  result: {view.get('result')}")
            print(f"  caps: {view.get('caps')}")
            print(f"  workspace keys: {sorted(view.get('workspace', {}))}")
            return 0
        session = ChatSession(
            operator=operator,
            input_fn=input,
            output_stream=sys.stdout,
            driver=None,  # default deterministic driver (mock path)
            on_result=lambda text: _append(transcript_file, f"{text}\n"),
        )

        # Persistent context: seed the transcript with the current context.
        _append(transcript_file, "\n## session\n")
        _append(transcript_file, f"context: {context_file}\n")

        while True:
            try:
                line = input("> ")
            except EOFError:
                break
            if line is None:
                break
            line = line.strip()
            if not line:
                continue
            if line == "!quit":
                break
            # Persistent context: every user line is appended to the context
            # file, then run as a requirement through the operator.
            _append(context_file, f"{line}\n")
            _append(transcript_file, f"> {line}\n")
            if not session.start_one(line):
                break
        return 0
    finally:
        runtime.stop()


if __name__ == "__main__":  # pragma: no cover - entry point
    raise SystemExit(main())