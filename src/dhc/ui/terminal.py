"""Prompt-only interactive terminal for dhc (adopts the reference pattern).

The reference project's terminal is deliberately NOT a full-screen TUI: no
Rich ``Live`` dashboard, no curses. It is a prompt-only REPL — one root agent
kept across turns, ``/``-commands for inspection, batch mode for non-TTY
pipelines — while status/tree/events are persisted to files (``agent_tree.json``,
``stats.json``, ``agents.txt``, ``events.jsonl``) for headless composability
and post-hoc manual review.

This module mirrors that pattern on dhc's committed surface:

* :class:`Terminal` — the REPL. Each line is a requirement run through the
  :class:`~dhc.operator.Operator` (the root door), or a ``/``-command.
  ``input_fn`` / ``output_stream`` are injectable so tests never touch real
  stdin/stdout.
* :func:`render_text_tree` — pure box-drawn tree renderer, reusing
  :func:`dhc.state.build_agent_tree` (which returns :class:`~dhc.state.AgentNode`
  view-models) and :func:`dhc.state.render_text_tree` for the line format.
* :func:`main` — CLI entry: ``python3 -m dhc.terminal``. Builds a fully-wired
  runtime via :func:`dhc.wiring.build_runtime`, attaches a
  :class:`~dhc.state.StateWriter` rooted at the artifact root's parent, and
  runs the terminal. ``--requirement`` runs once in batch mode.

No new dependencies: input uses plain ``input()`` (injectable), output is
plain text (no Rich markup).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from ..data.config import get_settings, load_config, merge_api_key
from .operator import Operator
from ..agent.state import StateWriter, build_agent_tree, build_stats, render_text_tree
from ..wiring import build_runtime

#: The prompt shown for each interactive input line.
PROMPT = ">>> "

#: How many trailing events.jsonl lines ``/events`` prints.
EVENTS_TAIL = 20


# --------------------------------------------------------------------------- #
# Pure rendering helpers
# --------------------------------------------------------------------------- #


def _fmt_artifact(artifact: Any) -> str:
    """One-line summary of an artifact (id + headline)."""
    aid = getattr(artifact, "id", None) or ""
    headline = getattr(artifact, "headline", None) or ""
    return f"{aid}  {headline}"


def _fmt_result(result: Any) -> str:
    """Render a settled Result as a single outcome line."""
    ok = bool(getattr(result, "ok", False))
    value = getattr(result, "value", None)
    reason = getattr(result, "reason", "") or ""
    if ok:
        return f"ok: {value}" if value is not None else "ok"
    return f"failed: {reason}" if reason else "failed"


def _fmt_stats(stats: Any) -> str:
    """Render a Stats view-model as a compact aggregate line."""
    agents = getattr(stats, "agents", 0)
    commits = getattr(stats, "commits", 0)
    tokens = getattr(stats, "tokens", 0)
    cost = getattr(stats, "cost_usd", 0.0) or 0.0
    parts = [f"agents {agents}"]
    if commits:
        parts.append(f"commits {commits}")
    if tokens:
        parts.append(f"tokens {tokens}")
    if cost:
        parts.append(f"cost ${cost:.4f}")
    return "  ".join(parts)


def _state_file_paths(writer: Optional[StateWriter]) -> list[str]:
    """The run-overview file paths persisted by *writer* (for batch output)."""
    if writer is None:
        return []
    return [
        str(writer.tree_path),
        str(writer.stats_path),
        str(writer.agents_txt_path),
        str(writer.events_path),
    ]


# --------------------------------------------------------------------------- #
# Terminal
# --------------------------------------------------------------------------- #


class Terminal:
    """Prompt-only interactive terminal (one root agent across turns).

    Constructor
    -----------
    - ``runtime`` — a fully-wired :class:`~dhc.runtime.Runtime` (see
      :func:`dhc.wiring.build_runtime`).
    - ``state_writer`` — optional :class:`~dhc.state.StateWriter` persisting
      the run-overview files; when omitted one is created at the artifact
      root's parent.
    - ``input_fn`` — callable returning one input line (defaults to
      ``input``); injectable for tests.
    - ``output_stream`` — anything with ``write(str)`` / ``flush()``
      (defaults to ``sys.stdout``); injectable for tests.

    ``run(requirement=None)`` is the main loop:

    * With a *requirement* (batch mode): run it once through the Operator,
      print the outcome + aggregate + state-file paths, return 0.
    * Without (interactive): keep ONE root agent across turns. Each line is a
      requirement run through the Operator (or a ``/``-command); Ctrl+C
      cancels the running agent; EOF (Ctrl+D) exits.

    ``/``-commands: ``/tree``, ``/agents``, ``/artifacts [id]``, ``/events``,
    ``/stats``, ``/resume <agent_id>``, ``/compact``, ``/help``, ``/quit``.
    """

    def __init__(
        self,
        runtime: Any,
        state_writer: Optional[StateWriter] = None,
        input_fn: Optional[Callable[[str], str]] = None,
        output_stream: Any = None,
    ) -> None:
        self.runtime = runtime
        self.state_writer = state_writer
        self.input_fn = input_fn if input_fn is not None else input
        self.output_stream = (
            output_stream if output_stream is not None else sys.stdout
        )
        #: The one root agent kept across turns (reference pattern).
        self.root_agent: Any = None
        # Prefer the WIRED operator (composition root): it carries the
        # question channel, so `ask_operator` questions asked mid-run by
        # agents actually reach the human at this terminal (INFO-023).
        wired = getattr(runtime, "operator", None)
        self._operator = wired if wired is not None else Operator(runtime=runtime)

    # -- output -------------------------------------------------------------

    def _write(self, text: str) -> None:
        self.output_stream.write(text)
        self.output_stream.flush()

    def _print(self, text: str = "") -> None:
        self._write(text + "\n")

    # -- input --------------------------------------------------------------

    def _read_input(self, prompt: str = PROMPT) -> str:
        """Read one input line via the injectable ``input_fn``."""
        return self.input_fn(prompt)

    # -- state helpers ------------------------------------------------------

    def _ensure_writer(self) -> StateWriter:
        """Return the StateWriter, creating one at the artifact root's parent."""
        if self.state_writer is None:
            settings = getattr(self.runtime, "settings", None)
            artifact_root = (
                getattr(settings, "artifact_root", None)
                if settings is not None
                else None
            )
            root = (
                Path(artifact_root).parent
                if artifact_root is not None
                else Path.cwd() / ".dynamic-harness"
            )
            self.state_writer = StateWriter(self.runtime, root=root)
        return self.state_writer

    def _snapshot(self) -> None:
        """Persist the run-overview files (best-effort)."""
        try:
            writer = self._ensure_writer()
            writer.snapshot(force=True)
            # events.jsonl is append-only (created on first event); ensure the
            # state-file set is complete for batch output and manual review.
            if not writer.events_path.exists():
                writer.events_path.touch()
        except Exception:  # noqa: BLE001 - a snapshot failure never breaks the REPL
            pass

    def _artifacts(self) -> list:
        """List artifact records from the runtime's artifact store."""
        store = getattr(self.runtime, "artifact_store", None)
        if store is None:
            return []
        try:
            return list(store.list_ids())
        except Exception:  # noqa: BLE001 - inspection must never crash
            return []

    def _artifact(self, artifact_id: str) -> Any:
        """Fetch one artifact by id (progressive disclosure tiers)."""
        store = getattr(self.runtime, "artifact_store", None)
        if store is None:
            return None
        try:
            return store.get(artifact_id)
        except Exception:  # noqa: BLE001 - inspection must never crash
            return None

    def _checkpoint(self, agent_id: str) -> Any:
        """Load an agent's persisted checkpoint, or None.

        This reads the **operator's** on-disk ``CheckpointStore``
        (``dhc.agent.checkpoint``) — the operator's resumability mechanism,
        surfaced via ``/resume``. It is deliberately separate from the
        agent's own workspace checkpoints (``state["checkpoints"]`` in the
        fabrication kit), which live in the agent's context. The split is
        intended (decision 0012, H-06); the on-disk store is not in the
        agent's context.
        """
        store = getattr(self.runtime, "checkpoint_store", None)
        if store is None:
            return None
        try:
            return store.load(agent_id)
        except Exception:  # noqa: BLE001 - inspection must never crash
            return None

    # -- /-commands ---------------------------------------------------------

    def _cmd_tree(self) -> None:
        """Print the agent tree as a box-drawn text tree."""
        try:
            nodes = build_agent_tree(self.runtime)
        except Exception as exc:  # noqa: BLE001 - inspection must never crash
            self._print(f"tree unavailable: {exc}")
            return
        self._print(render_text_tree(nodes).rstrip("\n"))

    def _cmd_agents(self) -> None:
        """List agents with status."""
        agents = getattr(self.runtime, "_agents", None)
        if not agents:
            self._print("(no agents)")
            return
        for agent_id in sorted(agents):
            agent = agents[agent_id]
            status = getattr(agent, "_status", None)
            status_value = (
                status.value if hasattr(status, "value") else str(status)
            )
            requirement = getattr(agent, "requirement", "") or ""
            self._print(f"{agent_id} [{status_value}] {requirement}")

    def _cmd_artifacts(self, arg: str) -> None:
        """List artifacts, or show one artifact's progressive disclosure."""
        if arg:
            artifact = self._artifact(arg.strip())
            if artifact is None:
                self._print(f"no artifact {arg.strip()!r}")
                return
            self._print(_fmt_artifact(artifact))
            summary = getattr(artifact, "summary", None)
            if summary:
                self._print(f"summary: {summary}")
            report = getattr(artifact, "report", None)
            if report is not None:
                self._print(f"report: {report}")
            return
        ids = self._artifacts()
        if not ids:
            self._print("(no artifacts)")
            return
        for artifact_id in ids:
            artifact = self._artifact(artifact_id)
            if artifact is None:
                self._print(artifact_id)
            else:
                self._print(_fmt_artifact(artifact))

    def _cmd_events(self) -> None:
        """Tail events.jsonl."""
        writer = self._ensure_writer()
        try:
            lines = writer.events_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            self._print("(no events yet)")
            return
        for line in lines[-EVENTS_TAIL:]:
            self._print(line)

    def _cmd_stats(self) -> None:
        """Print the aggregate stats."""
        try:
            stats = build_stats(self.runtime)
        except Exception as exc:  # noqa: BLE001 - inspection must never crash
            self._print(f"stats unavailable: {exc}")
            return
        self._print(_fmt_stats(stats))

    def _cmd_resume(self, arg: str) -> None:
        """Print an agent's persisted checkpoint if available."""
        agent_id = arg.strip()
        if not agent_id:
            self._print("usage: /resume <agent_id>")
            return
        checkpoint = self._checkpoint(agent_id)
        if checkpoint is None:
            self._print(f"no checkpoint for {agent_id}")
            return
        try:
            payload = checkpoint.model_dump_json(indent=2)
        except AttributeError:
            payload = json.dumps(
                checkpoint, ensure_ascii=False, indent=2, default=str
            )
        self._print(payload)

    def _cmd_compact(self) -> None:
        """Print a compact summary of the run."""
        try:
            stats = build_stats(self.runtime)
        except Exception:  # noqa: BLE001 - inspection must never crash
            stats = None
        agents = getattr(self.runtime, "_agents", None) or {}
        self._print(f"agents: {len(agents)}")
        if stats is not None:
            self._print(_fmt_stats(stats))
        writer = self._ensure_writer()
        self._print(f"state files: {', '.join(_state_file_paths(writer))}")

    def _cmd_help(self) -> None:
        self._print("Commands:")
        self._print("  /tree              print the agent tree (box-drawn text)")
        self._print("  /agents            list agents with status")
        self._print("  /artifacts [id]    list artifacts, or show one artifact")
        self._print("  /events            tail events.jsonl")
        self._print("  /stats             print the aggregate stats")
        self._print("  /resume <agent_id> print an agent's checkpoint")
        self._print("  /compact           print a compact summary")
        self._print("  /help              this help")
        self._print("  /quit              exit the terminal")
        self._print("Anything else is a requirement run through the Operator.")

    def _run_command(self, line: str) -> bool:
        """Dispatch a ``/``-command. Returns True if *line* was a command."""
        line = line.strip()
        if not line.startswith("/"):
            return False
        parts = line.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""
        if cmd == "/help":
            self._cmd_help()
        elif cmd == "/tree":
            self._cmd_tree()
        elif cmd == "/agents":
            self._cmd_agents()
        elif cmd == "/artifacts":
            self._cmd_artifacts(arg)
        elif cmd == "/events":
            self._cmd_events()
        elif cmd == "/stats":
            self._cmd_stats()
        elif cmd == "/resume":
            self._cmd_resume(arg)
        elif cmd == "/compact":
            self._cmd_compact()
        elif cmd in ("/quit", "/exit"):
            return False
        else:
            self._print(f"unknown command: {cmd}  (try /help)")
        return True

    # -- run ----------------------------------------------------------------

    def _run_requirement(self, requirement: str) -> Any:
        """Run one requirement through the Operator; return the Result.

        The terminal is the single root door across turns (reference pattern).
        dhc's committed runtime has no continuation hook (no ``submit_input``
        on a settled agent), so each requirement spawns a fresh root agent
        through the Operator; the first root is kept as :attr:`root_agent`
        for the ``/``-commands and continuity display.
        """
        result = self._operator.run(requirement)
        if self.root_agent is None:
            agents = getattr(self.runtime, "_agents", None) or {}
            if agents:
                self.root_agent = agents[sorted(agents)[0]]
        self._snapshot()
        return result

    def _print_batch(self, result: Any) -> None:
        """Batch-mode output: outcome + aggregate + state-file paths."""
        self._print(f"outcome: {_fmt_result(result)}")
        try:
            stats = build_stats(self.runtime)
            self._print(f"aggregate: {_fmt_stats(stats)}")
        except Exception:  # noqa: BLE001 - aggregate is best-effort
            pass
        writer = self._ensure_writer()
        self._print(f"state files: {', '.join(_state_file_paths(writer))}")

    def run(self, requirement: Optional[str] = None) -> int:
        """Run the terminal.

        With *requirement*: batch mode — run it once, print outcome +
        aggregate + state-file paths, return 0. Without: interactive REPL —
        one root agent across turns, ``/``-commands, Ctrl+C cancels the
        running agent, EOF exits. Returns the process exit code.
        """
        if requirement is not None:
            result = self._run_requirement(requirement)
            self._print_batch(result)
            return 0

        self._print("dhc — prompt-only terminal. Type a task, or /help.")
        while True:
            try:
                line = self._read_input(PROMPT)
            except (EOFError, KeyboardInterrupt):
                self._print()
                return 0
            if line is None:
                return 0
            line = line.strip()
            if not line:
                continue
            if line.lower() in ("exit", "quit", "/quit", "/exit"):
                return 0
            if self._run_command(line):
                continue
            try:
                result = self._run_requirement(line)
            except KeyboardInterrupt:
                # Ctrl+C cancels the running agent; return to the prompt.
                self._print("cancelled")
                continue
            self._print(f"outcome: {_fmt_result(result)}")


# --------------------------------------------------------------------------- #
# CLI entry
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser (exposed for tests)."""
    parser = argparse.ArgumentParser(
        prog="dhc.terminal",
        description="Prompt-only interactive terminal for the dhc agent harness.",
    )
    parser.add_argument(
        "--requirement",
        metavar="TEXT",
        help="Run this requirement once in batch mode, then exit.",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Force batch mode (non-interactive) even on a TTY.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use the deterministic mock driver (no API key needed).",
    )
    parser.add_argument(
        "--config",
        metavar="PATH",
        help="Path to harness.json (highest-precedence config layer; "
        "replaces the ./harness.json discovery layer)",
    )
    parser.add_argument("--model", help="LLM model name")
    parser.add_argument("--base-url", help="LLM API base URL")
    parser.add_argument("--api-key", help="LLM API key")
    return parser


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def _apply_provider_overrides(settings: Any, args: argparse.Namespace) -> None:
    """Apply --model/--base-url/--api-key to the settings' provider config.

    The settings object is a plain dataclass; ``provider`` is a read-only
    derived property over ``config.llm``. Overrides are applied by copying
    ``config.llm`` with the CLI values and stashing the new config on the
    settings instance so ``settings.provider`` reflects them.
    """
    if not (args.model or args.base_url or args.api_key):
        return
    provider = settings.provider
    updates: dict = {}
    if args.model:
        updates["model"] = args.model
    if args.base_url:
        updates["base_url"] = args.base_url
    if args.api_key:
        updates["api_key"] = args.api_key
    settings.config = settings.config.model_copy(
        update={"llm": provider.model_copy(update=updates)}
    )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry: build a wired runtime and run the Terminal.

    ``python3 -m dhc.terminal`` — interactive REPL by default; with
    ``--requirement TEXT`` (or ``--batch``) runs once in batch mode and
    prints outcome + aggregate + state-file paths. The runtime is built via
    :func:`dhc.wiring.build_runtime` with ``mock=not has_key`` (the mock path
    is chosen by the driver factory when no API key is present); a
    :class:`~dhc.state.StateWriter` is attached at the artifact root's parent.
    ``--config PATH`` loads an explicit ``harness.json`` as the
    highest-precedence config layer (see :func:`dhc.data.config.load_config`).
    """
    args = _parse_args(argv)
    settings = get_settings()
    # --config: load the explicit harness.json as the highest-precedence
    # config layer (XDG base -> explicit path) and install it on the
    # settings so settings.provider / settings.config.safety reflect it.
    # Without --config the settings keep the config discovered at
    # get_settings() time (XDG -> ./harness.json).
    if args.config is not None:
        settings.config = load_config(args.config)
    _apply_provider_overrides(settings, args)

    has_key = bool(args.api_key or merge_api_key())
    runtime = build_runtime(
        settings=settings,
        mock=args.mock or not has_key,
        artifact_root=settings.artifact_root,
    )
    runtime.start()

    writer = StateWriter(runtime, root=Path(settings.artifact_root).parent)
    writer.attach(runtime)

    terminal = Terminal(runtime, state_writer=writer)
    try:
        if args.requirement is not None or args.batch:
            requirement = args.requirement or ""
            return terminal.run(requirement)
        return terminal.run()
    except KeyboardInterrupt:
        terminal._print("Interrupted. Bye.")
        return 130
    finally:
        try:
            runtime.stop()
        except Exception:  # noqa: BLE001 - teardown must never mask the exit code
            pass


if __name__ == "__main__":
    sys.exit(main())