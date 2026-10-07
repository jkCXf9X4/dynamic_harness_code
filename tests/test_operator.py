"""Tests for dhc.operator and dhc.cli.

No real LLM, no real stdin: the operator's input_fn is scripted, the question
channel is a fake, and the CLI is driven with monkeypatched argv/input and
tmp_path files.
"""

import sys

import pytest

from dhc.cli import main
from dhc.models import Result
from dhc.operator import ChatSession, DefaultDriver, Operator
from dhc.runtime import Runtime


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
    op.steer("a1", "change course")
    assert messenger.sent == [("operator", "a1", "change course")]
    assert op.undelivered_steers == []


def test_steer_without_messenger_records_noop():
    op = Operator(runtime=None)
    op.steer("a1", "hello")
    assert op.undelivered_steers == [("a1", "hello")]


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


def test_chat_session_steer_calls_operator():
    rt = make_runtime()
    try:
        op = Operator(runtime=rt)
        stream = FakeStream()
        session = ChatSession(op, scripted_input("!steer a1 go left", "!quit"), stream)
        session.start()
        assert op.undelivered_steers == [("a1", "go left")]
        assert "steered a1" in stream.text
    finally:
        rt.stop()


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