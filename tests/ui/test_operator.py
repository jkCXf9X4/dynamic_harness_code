"""Tests for dhc.operator and dhc.cli.

No real LLM, no real stdin: the operator's input_fn is scripted, the question
channel is a fake, and the CLI is driven with monkeypatched argv/input and
tmp_path files.
"""

import sys

import pytest

from dhc.cli import main
from dhc.data.models import Result
from dhc.ui.operator import ChatSession, DefaultDriver, Operator
from dhc.framework.runtime import Runtime


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class FakeStream:
    """A write()/flush() sink capturing everything written."""

    def __init__(self) -> None:
        self.chunks: list[str] = []

    def write(self, text: str) -> None:
        self.chunks.append(text)

    def flush(self) -> None:
        pass

    @property
    def text(self) -> str:
        return "".join(self.chunks)


class FakeQuestionChannel:
    """Duck-typed question channel: pending_questions()/answer()."""

    def __init__(self, questions: list) -> None:
        self._questions = list(questions)
        self.answered: list[tuple] = []

    def pending_questions(self) -> list:
        return list(self._questions)

    def answer(self, question_event_id, answer: str):
        self.answered.append((question_event_id, answer))
        self._questions = [
            q for q in self._questions if _qid(q) != question_event_id
        ]


def _qid(q) -> str:
    payload = getattr(q, "payload", None)
    if isinstance(payload, dict) and "event_id" in payload:
        return payload["event_id"]
    return str(q)


def _question(event_id: str, text: str):
    class _Q:
        payload = {"event_id": event_id, "question": text}

    return _Q()


def make_runtime() -> Runtime:
    rt = Runtime()
    rt.start()
    return rt


def scripted_input(*lines):
    """Return an input_fn replaying *lines*, then returning None (EOF)."""
    it = iter(lines)

    def _fn(prompt: str) -> str:
        try:
            return next(it)
        except StopIteration:
            return None

    return _fn


# --------------------------------------------------------------------------- #
# Operator.run with the default driver
# --------------------------------------------------------------------------- #


def test_run_default_driver_settles_completed():
    rt = make_runtime()
    try:
        op = Operator(runtime=rt)
        result = op.run("write a haiku")
        assert isinstance(result, Result)
        assert result.done is True
        assert result.ok is True
        assert result.value == "write a haiku"
    finally:
        rt.stop()


def test_run_with_custom_driver():
    rt = make_runtime()
    try:
        op = Operator(runtime=rt)

        def driver(agent):
            if getattr(driver, "called", False):
                return None
            driver.called = True
            return "complete('custom done')"

        result = op.run("do the thing", driver=driver)
        assert result.ok is True
        assert result.value == "custom done"
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# stream_response
# --------------------------------------------------------------------------- #


def test_stream_response_writes_chunks_and_flushes():
    stream = FakeStream()
    op = Operator(runtime=None, stream=stream, chunk_size=4)
    op.stream_response("abcdefghij")
    assert stream.chunks == ["abcd", "efgh", "ij"]
    # Every chunk was flushed (flush is a no-op on the fake, but the call
    # must not raise and the stream must have been written).
    assert stream.text == "abcdefghij"


# --------------------------------------------------------------------------- #
# answer_questions
# --------------------------------------------------------------------------- #


def test_answer_questions_with_scripted_input():
    channel = FakeQuestionChannel(
        [_question("q1", "what color?"), _question("q2", "how many?")]
    )
    stream = FakeStream()
    op = Operator(
        runtime=None,
        question_channel=channel,
        stream=stream,
        input_fn=scripted_input("blue", "three"),
    )
    op.answer_questions(loop=True)
    assert channel.answered == [("q1", "blue"), ("q2", "three")]
    assert "[operator] what color?" in stream.text
    assert "[operator] how many?" in stream.text


def test_answer_questions_loop_false_answers_one():
    channel = FakeQuestionChannel([_question("q1", "one?"), _question("q2", "two?")])
    stream = FakeStream()
    op = Operator(
        runtime=None,
        question_channel=channel,
        stream=stream,
        input_fn=scripted_input("yes"),
    )
    op.answer_questions(loop=False)
    assert channel.answered == [("q1", "yes")]
    assert len(channel.pending_questions()) == 1


def test_answer_questions_no_channel_is_noop():
    op = Operator(runtime=None, question_channel=None, stream=FakeStream())
    op.answer_questions(loop=True)  # must not raise


# --------------------------------------------------------------------------- #
# steer
# --------------------------------------------------------------------------- #


class FakeMessenger:
    def __init__(self) -> None:
        self.sent: list[tuple] = []

    def send(self, sender_id: str, recipient_id: str, body: str):
        self.sent.append((sender_id, recipient_id, body))


def test_steer_with_messenger_delivers():
    messenger = FakeMessenger()
    op = Operator(runtime=None, messenger=messenger)
    delivered = op.steer("a1", "change course")
    assert delivered is True
    assert messenger.sent == [("operator", "a1", "change course")]
    assert op.undelivered_steers == []


def test_steer_without_messenger_records_noop():
    op = Operator(runtime=None)
    delivered = op.steer("a1", "hello")
    assert delivered is False
    assert op.undelivered_steers == [("a1", "hello")]


def test_steer_via_runtime_send_delivers():
    """W6.2 delivered path: a runtime with a working send() delivers."""
    rt = make_runtime()
    try:
        rt.spawn("a task", driver=DefaultDriver())
        op = Operator(runtime=rt)
        delivered = op.steer("a1", "go left")
        assert delivered is True
        assert op.undelivered_steers == []
    finally:
        rt.stop()


def test_steer_via_runtime_send_unknown_recipient_undelivered():
    """W6.2: runtime.send raises for an unknown recipient, so the steer
    falls back to the undelivered record (honesty, not a crash)."""
    rt = make_runtime()
    try:
        op = Operator(runtime=rt)
        delivered = op.steer("nope", "go left")
        assert delivered is False
        assert op.undelivered_steers == [("nope", "go left")]
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# ChatSession
# --------------------------------------------------------------------------- #


def test_chat_session_quit_exits():
    rt = make_runtime()
    try:
        op = Operator(runtime=rt)
        stream = FakeStream()
        session = ChatSession(op, scripted_input("!quit"), stream)
        session.start()
        assert stream.text == ""
    finally:
        rt.stop()


def test_chat_session_normal_line_runs_requirement():
    rt = make_runtime()
    try:
        op = Operator(runtime=rt)
        stream = FakeStream()
        session = ChatSession(op, scripted_input("hello world", "!quit"), stream)
        session.start()
        assert "hello world" in stream.text
    finally:
        rt.stop()


def test_chat_session_steer_undelivered_is_loud():
    """W6.2: with no messenger wired (the chat path), an undelivered steer
    must NOT print the success-looking 'steered <id>' — it names the no-op."""
    rt = make_runtime()
    try:
        op = Operator(runtime=rt)
        stream = FakeStream()
        session = ChatSession(op, scripted_input("!steer a1 go left", "!quit"), stream)
        session.start()
        assert op.undelivered_steers == [("a1", "go left")]
        assert "steer NOT delivered to a1 (no messenger wired)" in stream.text
        assert "steered a1" not in stream.text
    finally:
        rt.stop()


def test_chat_session_steer_delivered_prints_success():
    """W6.2 delivered path: a messenger wired on the operator delivers, and
    the success message stays honest ('steered <id>')."""
    rt = make_runtime()
    try:
        messenger = FakeMessenger()
        op = Operator(runtime=rt, messenger=messenger)
        stream = FakeStream()
        session = ChatSession(op, scripted_input("!steer a1 go left", "!quit"), stream)
        session.start()
        assert messenger.sent == [("operator", "a1", "go left")]
        assert op.undelivered_steers == []
        assert "steered a1" in stream.text
        assert "NOT delivered" not in stream.text
    finally:
        rt.stop()


def test_chat_session_inspect_unknown_id_is_named():
    """W6.3: !inspect on an unknown agent id names it loudly instead of
    printing a blank 'status: None' view."""
    rt = make_runtime()
    try:
        op = Operator(runtime=rt)
        stream = FakeStream()
        session = ChatSession(
            op, scripted_input("!inspect nope", "!quit"), stream
        )
        session.start()
        assert "unknown agent id: nope (0 agents known)" in stream.text
        assert "status: None" not in stream.text
    finally:
        rt.stop()


def test_chat_session_inspect_known_id_prints_view():
    """W6.3: !inspect on a known agent id still prints the read-only view."""
    rt = make_runtime()
    try:
        rt.spawn("a task", driver=DefaultDriver())
        op = Operator(runtime=rt)
        stream = FakeStream()
        session = ChatSession(op, scripted_input("!inspect a1", "!quit"), stream)
        session.start()
        assert "inspect a1" in stream.text
        assert "unknown agent id" not in stream.text
    finally:
        rt.stop()


def test_chat_banner_lists_all_in_loop_commands():
    """W6.3: the chat banner lists !quit, !steer and !inspect, each with
    one-line help, rendered from ChatSession.COMMANDS."""
    for cmd, help_ in ChatSession.COMMANDS:
        assert cmd in ("!quit", "!steer <agent_id> <message>",
                       "!inspect <agent_id>")
        assert help_  # every command carries one-line help
    # The banner renders every command line verbatim.
    banner_lines = [f"  {cmd} — {help_}" for cmd, help_ in ChatSession.COMMANDS]
    for line in banner_lines:
        assert line
    # And the dispatch in start_one covers exactly the advertised set.
    assert [cmd.split()[0] for cmd, _ in ChatSession.COMMANDS] == [
        "!quit", "!steer", "!inspect"
    ]


def test_chat_session_eof_exits():
    rt = make_runtime()
    try:
        op = Operator(runtime=rt)
        stream = FakeStream()
        session = ChatSession(op, scripted_input(), stream)
        session.start()
        assert stream.text == ""
    finally:
        rt.stop()


def test_chat_session_echo_banner_on_default_driver():
    """D3: with the DefaultDriver fallback (driver=None) the first
    requirement line prints the one-line echo-mode banner, exactly once."""
    rt = make_runtime()
    try:
        op = Operator(runtime=rt)
        stream = FakeStream()
        session = ChatSession(op, scripted_input("hello", "again", "!quit"), stream)
        session.start()
        banner = (
            'echo mode: no LLM driver wired — set OPENAI_API_KEY and use '
            '"python3 -m dhc.ui.terminal" for the real driver'
        )
        assert stream.text.count(banner) == 1
        # The banner precedes the first echoed result.
        assert stream.text.index(banner) < stream.text.index("hello")
    finally:
        rt.stop()


def test_chat_session_no_echo_banner_with_real_driver():
    """D3: when a real driver is wired, no echo-mode banner is printed."""
    rt = make_runtime()
    try:
        op = Operator(runtime=rt)

        def driver(agent):
            if getattr(driver, "called", False):
                return None
            driver.called = True
            return "complete('custom done')"

        stream = FakeStream()
        session = ChatSession(
            op, scripted_input("hello", "!quit"), stream, driver=driver
        )
        session.start()
        assert "echo mode" not in stream.text
        assert "custom done" in stream.text
    finally:
        rt.stop()


# --------------------------------------------------------------------------- #
# cli.main
# --------------------------------------------------------------------------- #


def test_cli_main_mock_writes_transcript(tmp_path, monkeypatch):
    context_file = tmp_path / "context.md"
    transcript_file = tmp_path / "transcript.md"
    # Script the input: one requirement, then quit.
    lines = iter(["build a thing", "!quit"])

    def fake_input(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            return None

    monkeypatch.setattr("builtins.input", fake_input)
    rc = main(
        [
            "--mock",
            "--context",
            str(context_file),
            "--transcript",
            str(transcript_file),
        ]
    )
    assert rc == 0
    assert context_file.exists()
    assert transcript_file.exists()
    transcript = transcript_file.read_text(encoding="utf-8")
    assert "> build a thing" in transcript
    assert "build a thing" in transcript  # the settled result text
    context = context_file.read_text(encoding="utf-8")
    assert "build a thing" in context


def test_cli_main_creates_missing_files(tmp_path, monkeypatch):
    context_file = tmp_path / "nested" / "context.md"
    transcript_file = tmp_path / "nested" / "transcript.md"
    lines = iter(["!quit"])

    def fake_input(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            return None

    monkeypatch.setattr("builtins.input", fake_input)
    rc = main(
        [
            "--mock",
            "--context",
            str(context_file),
            "--transcript",
            str(transcript_file),
        ]
    )
    assert rc == 0
    assert context_file.exists()
    assert transcript_file.exists()


def test_cli_main_importable_without_api_key():
    # Importing the module and building the parser must not require a key.
    import dhc.cli as cli

    parser = cli.build_parser()
    args = parser.parse_args(["--mock"])
    assert args.mock is True


def test_cli_timeout_flag_removed():
    """H-02: --timeout is gone — the chat CLI always runs the deterministic
    driver, so a per-call LLM timeout had no consumer. The real driver's
    timeout is configured via llm.call_timeout_seconds in harness.json."""
    import dhc.cli as cli

    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--timeout", "30"])
    assert "timeout" not in parser.format_help()


def test_cli_model_flag_removed():
    """W6.4: --model is gone from the chat CLI — it only ever fed the banner
    text (the chat CLI never calls an LLM, INFO-070). The real driver's model
    is configured via llm.model in harness.json or --model on the terminal."""
    import dhc.cli as cli

    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--model", "gpt-4o"])
    assert "--model" not in parser.format_help()
    # --mock stays (README quickstart parity) but is a documented no-op.
    args = parser.parse_args(["--mock"])
    assert args.mock is True
    assert "--mock" in parser.format_help()


def test_cli_config_flag_loads_explicit_harness_json(tmp_path, monkeypatch):
    """W5.4: --config PATH loads that harness.json into the runtime's settings
    (parity with the terminal entry point)."""
    import json

    import dhc.cli as cli

    monkeypatch.setenv("DHC_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("DHC_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    cfg = tmp_path / "harness.json"
    cfg.write_text(json.dumps({"llm": {"model": "w54-test-model"}}), encoding="utf-8")

    captured = {}

    def fake_runtime(**kwargs):
        captured["settings"] = kwargs.get("settings")
        rt = type("RT", (), {"start": lambda self: None, "stop": lambda self: None})()
        return rt

    monkeypatch.setattr(cli, "Runtime", fake_runtime)
    lines = iter(["!quit"])

    def fake_input(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            return None

    monkeypatch.setattr("builtins.input", fake_input)
    rc = cli.main(
        [
            "--mock",
            "--config",
            str(cfg),
            "--context",
            str(tmp_path / "context.md"),
            "--transcript",
            str(tmp_path / "transcript.md"),
        ]
    )
    assert rc == 0
    settings = captured["settings"]
    assert settings is not None
    assert settings.provider.model == "w54-test-model"


def test_cli_config_flag_missing_file_raises(tmp_path, monkeypatch):
    """W5.4: a missing explicit --config file raises (not a silent no-op)."""
    import dhc.cli as cli

    monkeypatch.setenv("DHC_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("DHC_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    with pytest.raises(Exception):
        cli.main(
            [
                "--mock",
                "--config",
                str(tmp_path / "nope.json"),
                "--context",
                str(tmp_path / "context.md"),
                "--transcript",
                str(tmp_path / "transcript.md"),
            ]
        )


def test_cli_parser_exposes_config_flag():
    """W5.4: build_parser() exposes --config (help text matches the wiring)."""
    import dhc.cli as cli

    parser = cli.build_parser()
    args = parser.parse_args(["--config", "harness.json"])
    assert args.config == "harness.json"
    assert "--config" in parser.format_help()


def test_cli_banner_lists_all_in_loop_commands(tmp_path, monkeypatch):
    """W6.3: the chat CLI banner lists !quit, !steer and !inspect with
    one-line help each (rendered from ChatSession.COMMANDS)."""
    import io

    import dhc.cli as cli

    monkeypatch.setenv("DHC_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("DHC_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    lines = iter(["!quit"])

    def fake_input(prompt=""):
        try:
            return next(lines)
        except StopIteration:
            return None

    monkeypatch.setattr("builtins.input", fake_input)
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    rc = cli.main(
        [
            "--mock",
            "--context",
            str(tmp_path / "context.md"),
            "--transcript",
            str(tmp_path / "transcript.md"),
        ]
    )
    assert rc == 0
    banner = captured.getvalue()
    for cmd, help_ in ChatSession.COMMANDS:
        assert cmd in banner
        assert help_ in banner
    assert "commands:" in banner


def test_cli_inspect_unknown_id_is_named(tmp_path, monkeypatch):
    """W6.3: --inspect on an unknown agent id names it loudly instead of
    printing a blank 'status: None' view."""
    import io

    import dhc.cli as cli

    monkeypatch.setenv("DHC_WORKSPACE_ROOT", str(tmp_path))
    monkeypatch.setenv("DHC_ARTIFACT_ROOT", str(tmp_path / "artifacts"))
    captured = io.StringIO()
    monkeypatch.setattr("sys.stdout", captured)
    rc = cli.main(
        [
            "--mock",
            "--inspect",
            "nope",
            "--context",
            str(tmp_path / "context.md"),
            "--transcript",
            str(tmp_path / "transcript.md"),
        ]
    )
    assert rc == 0
    out = captured.getvalue()
    assert "unknown agent id: nope (0 agents known)" in out
    assert "status: None" not in out

# --------------------------------------------------------------------------- #
# IMP-001 Step 5: operator.inspect — read-only window into a live workspace
# --------------------------------------------------------------------------- #


def test_operator_inspect_readonly(tmp_path):
    """Operator.inspect returns a workspace view without mutating anything."""
    import time

    from dhc.data.config import Settings
    from dhc.llm.driver import MockDriver
    from dhc.data.models import AgentStatus
    from dhc.wiring import build_runtime

    settings = Settings(workspace_root=tmp_path, artifact_root=tmp_path)
    rt = build_runtime(mock=True, artifact_root=tmp_path, settings=settings)
    rt.start()
    try:
        handle = rt.spawn(
            "inspect me",
            driver=MockDriver(
                [
                    "x = 1\nstate['marker'] = 'set'\ncontext.guardrails['budget'] = 1\n",
                    "import time\ntime.sleep(0.3)\ncomplete('done')\n",
                ]
            ),
        )
        # Wait until the first block has run (workspace carries the marker).
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if (
                rt.repl_engine.globals_for(handle.id)
                .get("state", {})
                .get("marker")
                == "set"
            ):
                break
            time.sleep(0.005)
        op = Operator(runtime=rt)
        before = rt.repl_engine.globals_for(handle.id)
        view = op.inspect(handle.id)
        after = rt.repl_engine.globals_for(handle.id)
        # The view carries a workspace copy + status/result/caps digest.
        assert "workspace" in view
        assert view["workspace"]["state"]["marker"] == "set"
        assert view["workspace"]["context"].guardrails.get("budget") == 1
        assert view["status"] in (
            AgentStatus.running.value,
            AgentStatus.completed.value,
        )
        assert isinstance(view["caps"], dict)
        assert "max_workspace_bytes" in view["caps"]
        # The workspace was NOT mutated by inspect (no new keys, no state
        # change) and the agent keeps running.
        assert set(before) == set(after)
        assert dict(before["state"]) == dict(after["state"])
        assert before["context"].guardrails == after["context"].guardrails
        completion = handle.await_()
        assert completion.status == AgentStatus.completed
        assert completion.summary == "done"
    finally:
        rt.stop()
