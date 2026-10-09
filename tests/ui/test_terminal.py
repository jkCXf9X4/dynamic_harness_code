"""Tests for dhc.terminal — the prompt-only interactive terminal.

Uses injectable ``input_fn`` / ``output_stream`` and pytest ``tmp_path`` —
never real stdin/stdout, never repo writes. The runtime is the fully-wired
:func:`dhc.wiring.build_runtime` over a temp artifact root with the
deterministic mock path (no API key, no network).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from dhc.framework.agent import Agent
from dhc.llm.driver import MockDriver
from dhc.ui.state import AgentNode, StateWriter, build_agent_tree
from dhc.ui import terminal as terminal_module
from dhc.ui.terminal import Terminal, main, render_text_tree
from dhc.wiring import build_runtime


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class ScriptedInput:
    """An input_fn replaying a fixed script of lines, then EOF."""

    def __init__(self, *lines: str) -> None:
        self.lines = list(lines)
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if not self.lines:
            raise EOFError
        return self.lines.pop(0)


class Output:
    """A StringIO-like output stream capturing writes."""

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def write(self, text: str) -> None:
        self.chunks.append(text)

    def flush(self) -> None:
        pass

    @property
    def text(self) -> str:
        return "".join(self.chunks)


def make_runtime(tmp_path: Path):
    """A fully-wired runtime over a fresh temp artifact root (mock path)."""
    rt = build_runtime(mock=True, artifact_root=tmp_path / "artifacts")
    rt.start()
    return rt


def make_terminal(tmp_path: Path, *lines: str):
    """A Terminal with a scripted input and a captured output stream."""
    rt = make_runtime(tmp_path)
    writer = StateWriter(rt, root=tmp_path / "run")
    term = Terminal(
        rt,
        state_writer=writer,
        input_fn=ScriptedInput(*lines),
        output_stream=Output(),
    )
    return rt, writer, term


def run_script(tmp_path: Path, *lines: str) -> tuple[Terminal, Output, int]:
    """Run a scripted interactive session; return (terminal, output, code)."""
    rt, writer, term = make_terminal(tmp_path, *lines)
    code = term.run()
    return term, term.output_stream, code


# --------------------------------------------------------------------------- #
# render_text_tree — pure function
# --------------------------------------------------------------------------- #


def test_render_text_tree_single_node():
    nodes = [AgentNode(agent_id="a1", description="root task", status="completed")]
    text = render_text_tree(nodes)
    assert "└ a1 [completed] root task" in text


def test_render_text_tree_nested_branches():
    nodes = [
        AgentNode(
            agent_id="a1",
            description="root task",
            status="running",
            children=[
                AgentNode(
                    agent_id="a2",
                    description="child task",
                    status="completed",
                ),
                AgentNode(
                    agent_id="a3",
                    description="sibling task",
                    status="failed",
                ),
            ],
        )
    ]
    text = render_text_tree(nodes)
    lines = text.splitlines()
    assert lines[0] == "└ a1 [running] root task"
    assert lines[1] == "  ├ a2 [completed] child task"
    assert lines[2] == "  └ a3 [failed] sibling task"


def test_render_text_tree_empty():
    assert render_text_tree([]) == "(no agents)\n"


def test_render_text_tree_clips_long_description():
    nodes = [
        AgentNode(
            agent_id="a1",
            description="x" * 100,
            status="completed",
        )
    ]
    text = render_text_tree(nodes)
    # short_description clips at 40 chars with a word-boundary ellipsis.
    assert len(text.strip()) < 60
    assert "…" in text


# --------------------------------------------------------------------------- #
# /-commands
# --------------------------------------------------------------------------- #


def test_tree_command_prints_box_drawn_tree(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "do the thing", "/tree", "/quit")
    code = term.run()
    assert code == 0
    assert "└" in term.output_stream.text
    assert "[" in term.output_stream.text
    assert "a1 [completed]" in term.output_stream.text


def test_agents_command_lists_agents(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "/agents", "/quit")
    code = term.run()
    assert code == 0
    assert "(no agents)" in term.output_stream.text


def test_agents_command_lists_spawned_agent(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "/agents", "/quit")
    rt.spawn("a task", driver=MockDriver.single("complete('done')"))
    rt.await_("a1")
    code = term.run()
    assert code == 0
    assert "a1 [completed] a task" in term.output_stream.text


def test_artifacts_command_lists_and_shows_disclosure(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "/artifacts", "/quit")
    # Publish an artifact through the real store.
    store = rt.artifact_store
    art = store.publish("hello", "a summary", "the full report body")
    code = term.run()
    text = term.output_stream.text
    assert code == 0
    assert art.id in text
    assert "hello" in text


def test_artifacts_command_with_id_shows_progressive_disclosure(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "/artifacts", "/quit")
    store = rt.artifact_store
    art = store.publish("hello", "a summary", "the full report body")
    term = Terminal(
        rt,
        state_writer=writer,
        input_fn=ScriptedInput(f"/artifacts {art.id}", "/quit"),
        output_stream=Output(),
    )
    code = term.run()
    text = term.output_stream.text
    assert code == 0
    assert art.id in text
    assert "hello" in text
    assert "a summary" in text
    assert "the full report body" in text


def test_stats_command_prints_stats(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "/stats", "/quit")
    code = term.run()
    assert code == 0
    assert "agents" in term.output_stream.text


def test_events_command_tails_events_jsonl(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "/events", "/quit")
    writer.append_event({"event": "activity", "agent_id": "a1", "event_type": "turn_started"})
    code = term.run()
    assert code == 0
    assert "turn_started" in term.output_stream.text


def test_compact_command_prints_summary(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "/compact", "/quit")
    code = term.run()
    assert code == 0
    assert "agents:" in term.output_stream.text
    assert "state files:" in term.output_stream.text


def test_help_command_lists_commands(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "/help", "/quit")
    code = term.run()
    assert code == 0
    for cmd in ("/tree", "/agents", "/artifacts", "/events", "/stats",
                "/resume", "/compact", "/help", "/quit"):
        assert cmd in term.output_stream.text


def test_unknown_command_prints_help_hint(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "/bogus", "/quit")
    code = term.run()
    assert code == 0
    assert "unknown command" in term.output_stream.text


def test_quit_exits(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "/quit")
    code = term.run()
    assert code == 0


def test_quit_lowercase_exits(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "quit")
    code = term.run()
    assert code == 0


# --------------------------------------------------------------------------- #
# Interactive requirement lines
# --------------------------------------------------------------------------- #


def test_requirement_line_runs_root_agent_and_settles(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "do the thing", "/quit")
    code = term.run()
    assert code == 0
    # The mock path settles the root as completed with the requirement value.
    assert "outcome: ok: do the thing" in term.output_stream.text
    # The root agent is kept across turns.
    assert term.root_agent is not None
    assert term.root_agent.id == "a1"


def test_requirement_line_keeps_one_root_agent_across_turns(tmp_path):
    rt, writer, term = make_terminal(
        tmp_path, "first task", "second task", "/quit"
    )
    code = term.run()
    assert code == 0
    assert "outcome: ok: first task" in term.output_stream.text
    assert "outcome: ok: second task" in term.output_stream.text
    # The terminal keeps the first root agent as its continuity anchor.
    assert term.root_agent is not None
    assert term.root_agent.id == "a1"


def test_eof_exits_cleanly(tmp_path):
    rt, writer, term = make_terminal(tmp_path)
    code = term.run()
    assert code == 0


def test_blank_lines_are_ignored(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "", "   ", "/quit")
    code = term.run()
    assert code == 0


# --------------------------------------------------------------------------- #
# Batch mode
# --------------------------------------------------------------------------- #


def test_batch_mode_prints_outcome_aggregate_and_state_files(tmp_path):
    rt, writer, term = make_terminal(tmp_path)
    code = term.run("do the thing")
    text = term.output_stream.text
    assert code == 0
    assert "outcome: ok: do the thing" in text
    assert "aggregate:" in text
    assert "state files:" in text
    for path in (writer.tree_path, writer.stats_path, writer.agents_txt_path,
                 writer.events_path):
        assert str(path) in text


def test_batch_mode_persists_state_files(tmp_path):
    rt, writer, term = make_terminal(tmp_path)
    code = term.run("do the thing")
    assert code == 0
    assert writer.tree_path.exists()
    assert writer.stats_path.exists()
    assert writer.agents_txt_path.exists()
    assert writer.events_path.exists()
    tree = json.loads(writer.tree_path.read_text())
    assert tree and tree[0]["status"] == "completed"


# --------------------------------------------------------------------------- #
# main() CLI entry
# --------------------------------------------------------------------------- #


def test_main_batch_requirement(tmp_path, monkeypatch):
    """main() with --requirement runs batch mode and exits 0."""
    monkeypatch.setenv("DHC_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("DHC_WORKSPACE_ROOT", str(tmp_path))
    code = main(["--requirement", "do the thing", "--mock"])
    assert code == 0


def test_main_batch_flag(tmp_path, monkeypatch):
    """main() with --batch runs batch mode and exits 0."""
    monkeypatch.setenv("DHC_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("DHC_WORKSPACE_ROOT", str(tmp_path))
    code = main(["--batch", "--mock"])
    assert code == 0


def test_main_unknown_flag_raises_system_exit(tmp_path, monkeypatch):
    monkeypatch.setenv("DHC_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    with pytest.raises(SystemExit):
        main(["--bogus"])


# --------------------------------------------------------------------------- #
# H-02: --config is wired (highest-precedence harness.json layer)
# --------------------------------------------------------------------------- #


def test_main_config_flag_loads_explicit_harness_json(tmp_path, monkeypatch):
    """--config PATH loads that harness.json into the runtime's settings."""
    monkeypatch.setenv("DHC_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("DHC_WORKSPACE_ROOT", str(tmp_path))
    cfg = tmp_path / "harness.json"
    cfg.write_text(
        json.dumps({"llm": {"model": "h02-test-model"}}), encoding="utf-8"
    )
    captured = {}

    real_build_runtime = terminal_module.build_runtime

    def spy_build_runtime(**kwargs):
        captured["settings"] = kwargs.get("settings")
        return real_build_runtime(**kwargs)

    monkeypatch.setattr(terminal_module, "build_runtime", spy_build_runtime)
    code = main(["--requirement", "do the thing", "--mock", "--config", str(cfg)])
    assert code == 0
    settings = captured["settings"]
    assert settings is not None
    assert settings.provider.model == "h02-test-model"


def test_main_config_flag_missing_file_raises(tmp_path, monkeypatch):
    """A missing explicit --config file raises (not a silent no-op)."""
    monkeypatch.setenv("DHC_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("DHC_WORKSPACE_ROOT", str(tmp_path))
    with pytest.raises(Exception):
        main(["--requirement", "x", "--mock", "--config", str(tmp_path / "nope.json")])


def test_main_model_override_applies_to_provider(tmp_path, monkeypatch):
    """--model reaches settings.provider (the read-only property is honored)."""
    monkeypatch.setenv("DHC_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    monkeypatch.setenv("DHC_WORKSPACE_ROOT", str(tmp_path))
    captured = {}

    real_build_runtime = terminal_module.build_runtime

    def spy_build_runtime(**kwargs):
        captured["settings"] = kwargs.get("settings")
        return real_build_runtime(**kwargs)

    monkeypatch.setattr(terminal_module, "build_runtime", spy_build_runtime)
    code = main(["--requirement", "x", "--mock", "--model", "h02-cli-model"])
    assert code == 0
    assert captured["settings"].provider.model == "h02-cli-model"


def test_terminal_parser_still_accepts_config_flag():
    """build_parser() exposes --config (help text matches the wired behavior)."""
    parser = terminal_module.build_parser()
    args = parser.parse_args(["--config", "harness.json"])
    assert args.config == "harness.json"
    help_text = parser.format_help()
    assert "--config" in help_text
    assert "harness.json" in help_text


# --------------------------------------------------------------------------- #
# Ctrl+C / cancellation
# --------------------------------------------------------------------------- #


def test_keyboard_interrupt_during_requirement_returns_to_prompt(tmp_path):
    """Ctrl+C while a requirement runs cancels the run, not the terminal."""

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    rt = make_runtime(tmp_path)
    writer = StateWriter(rt, root=tmp_path / "run")
    out = Output()
    term = Terminal(
        rt,
        state_writer=writer,
        input_fn=ScriptedInput("do the thing", "/quit"),
        output_stream=out,
    )
    # Simulate Ctrl+C arriving while the requirement is running: the
    # Operator's blocking run raises KeyboardInterrupt, which the terminal
    # catches and reports as a cancellation, then returns to the prompt.
    term._operator.run = interrupt  # type: ignore[method-assign]
    code = term.run()
    assert code == 0
    assert "cancelled" in out.text


def test_keyboard_interrupt_at_prompt_exits(tmp_path):
    """Ctrl+C at the idle prompt exits cleanly."""

    class InterruptingInput:
        def __call__(self, prompt: str) -> str:
            raise KeyboardInterrupt

    rt = make_runtime(tmp_path)
    writer = StateWriter(rt, root=tmp_path / "run")
    out = Output()
    term = Terminal(rt, state_writer=writer, input_fn=InterruptingInput(), output_stream=out)
    code = term.run()
    assert code == 0


def test_input_none_exits(tmp_path):
    """An input_fn returning None (EOF) exits cleanly."""
    rt, writer, term = make_terminal(tmp_path)
    term.input_fn = lambda prompt: None  # type: ignore[assignment]
    code = term.run()
    assert code == 0


# --------------------------------------------------------------------------- #
# StateWriter integration
# --------------------------------------------------------------------------- #


def test_state_writer_attached_snapshots_after_run(tmp_path):
    rt, writer, term = make_terminal(tmp_path, "do the thing", "/quit")
    code = term.run()
    assert code == 0
    assert writer.tree_path.exists()
    assert writer.stats_path.exists()
    assert writer.agents_txt_path.exists()
    assert writer.events_path.exists()


def test_tree_command_reflects_runtime_agents(tmp_path):
    """/tree after a run shows the settled root with its status."""
    rt, writer, term = make_terminal(tmp_path, "do the thing", "/tree", "/quit")
    code = term.run()
    assert code == 0
    text = term.output_stream.text
    assert "a1 [completed]" in text
    assert "do the thing" in text


# --------------------------------------------------------------------------- #
# render_text_tree against build_agent_tree (integration)
# --------------------------------------------------------------------------- #


def test_render_text_tree_from_build_agent_tree(tmp_path):
    rt = make_runtime(tmp_path)
    rt.spawn("root task", driver=MockDriver.single("complete('done')"))
    rt.await_("a1")
    nodes = build_agent_tree(rt)
    text = render_text_tree(nodes)
    assert "a1 [completed] root task" in text