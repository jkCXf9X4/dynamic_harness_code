"""Minimal chat-only TUI for dhc (INFO-028).

The CLI is deliberately thin: it wires the :class:`~dhc.operator.Operator`
and :class:`~dhc.operator.ChatSession` to two persistent files — a context
file holding the current requirement/context and a transcript file holding
the conversation — and renders a banner plus the streamed responses. All chat
semantics live in ``dhc.operator``.

The chat CLI always runs the deterministic default driver (``driver=None``)
— it never calls an LLM (INFO-070) — so every requirement settles with a
coded ``complete(requirement)`` action. ``--mock`` is accepted for
quickstart parity but is a documented no-op; ``--model`` was removed (W6.4)
because the chat CLI has no real driver to configure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from .data.config import get_settings, load_config
from .ui.operator import ChatSession, Operator
from .framework.runtime import Runtime


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


def _banner(stream: object) -> None:
    """Print the startup banner to *stream* (rich when available).

    The chat CLI always runs the deterministic driver (echo mode) — the
    banner says so (F8 honesty: it used to print ``model=...`` from a
    decorative ``--model`` flag that never reached a driver). The banner
    lists every in-loop command with one-line help (W6.3), rendered from
    :data:`ChatSession.COMMANDS`, the single source of truth for the chat
    vocabulary, so the banner cannot drift from the dispatch.
    """
    command_lines = [f"  {cmd} — {help_}" for cmd, help_ in ChatSession.COMMANDS]
    try:
        from rich.console import Console

        console = Console(file=stream)
        console.rule("[bold cyan]dhc[/bold cyan]")
        console.print(
            "[dim]operator door open — echo mode (deterministic driver; "
            "no LLM in dhc chat)[/dim]"
        )
        console.print("[dim]commands:[/dim]")
        for line in command_lines:
            console.print(f"[dim]{line}[/dim]")
    except Exception:  # noqa: BLE001 - rich is optional for the banner
        stream.write("dhc — operator door open\n")
        stream.write("mode: echo (deterministic driver; no LLM in dhc chat)\n")
        stream.write("commands:\n")
        for line in command_lines:
            stream.write(f"{line}\n")
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
        help="accepted for quickstart parity; the chat CLI always runs the "
        "deterministic driver (no LLM in dhc chat)",
    )
    # NOTE (W6.4): --model was removed — the chat CLI always runs the
    # deterministic driver (driver=None), so a model name had no consumer
    # beyond the banner text. The real driver's model is configured via
    # llm.model in harness.json (or --model on the terminal entry point).
    parser.add_argument(
        "--config",
        default=None,
        help="Path to harness.json (highest-precedence config layer; "
        "see dhc.data.config.load_config)",
    )
    # NOTE (H-02): --timeout was removed — the chat CLI always runs the
    # deterministic driver (driver=None), so a per-call LLM timeout had no
    # consumer. The real driver's timeout is configured via
    # llm.call_timeout_seconds in harness.json (or DHC_LLM_TIMEOUT_SECONDS).
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
    # --config: load the explicit harness.json as the highest-precedence
    # config layer (XDG base -> explicit path) and install it on the
    # settings so settings.provider / settings.config.safety reflect it
    # (parity with the terminal entry point, W5.4).
    if args.config is not None:
        settings.config = load_config(args.config)

    # The chat CLI always runs the deterministic driver (driver=None) —
    # it never calls an LLM (INFO-070). --mock is accepted for quickstart
    # parity (README) but is a documented no-op; --model was removed (W6.4).
    _banner(sys.stdout)

    runtime = Runtime(settings=settings)
    runtime.start()
    try:
        operator = Operator(runtime=runtime, stream=sys.stdout)
        if args.inspect is not None:
            view = operator.inspect(args.inspect)
            if view.get("status") is None:
                # F8 honesty: an unknown id is named loudly, not rendered
                # as a blank "status: None" view.
                known = len(getattr(runtime, "_agents", None) or {})
                print(
                    f"unknown agent id: {args.inspect} "
                    f"({known} agents known)"
                )
                return 0
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