"""The operator surface: the single human<->mesh door.

This module owns the root door (INFO-017), the continuous chat loop with
mid-turn steering (INFO-022), operator-question answering (INFO-023), and
streaming responses (INFO-022). The CLI (``dhc.cli``) is only rendering; all
chat semantics live here.

The operator is the **only** boundary between the human and the agent mesh:
requests enter at the root agent, the root's final result returns to the
operator, and inner agents reach the operator only up the parent chain (with
the one carve-out of the question channel, INFO-023).

Design notes
------------
* ``Operator`` is duck-typed against the runtime and the question channel —
  nothing here imports sibling work-in-progress modules at module level, so
  this module is importable standalone and testable with fakes.
* ``run()`` spawns a root agent and drives it to settlement. The default
  driver is a deterministic coded action (``complete(requirement)``) so the
  operator works without an API key; the real LLM driver is wired by the
  integration agent.
* ``steer()`` injects a message into a running agent's context. The committed
  runtime has no steer hook, so steering is implemented via an injected
  duck-typed messenger (``messenger.send(...)``) when one is provided, and is
  otherwise a documented no-op that records the message on the operator.
* ``answer_questions()`` polls the question channel and answers pending
  operator questions from an injectable ``input_fn`` (never real stdin in
  tests).
"""

from __future__ import annotations

import sys
import time
from typing import Any, Callable, Optional

from ..data.models import Result


# --------------------------------------------------------------------------- #
# Default driver
# --------------------------------------------------------------------------- #


class DefaultDriver:
    """Deterministic driver: one coded action, then settle.

    The first call returns a block that runs the in-code ``complete(
    requirement)`` verb; the second call returns ``None`` so the runtime
    settles the root as *completed* with the requirement as its value. This
    is the mock path that makes the operator usable without an API key; the
    real LLM driver is wired by the integration agent.
    """

    def __init__(self) -> None:
        self._calls = 0

    def __call__(self, agent: Any) -> Optional[str]:
        if self._calls > 0:
            return None
        self._calls += 1
        return (
            "requirement = agent.requirement\n"
            "complete(requirement)\n"
        )


# --------------------------------------------------------------------------- #
# Question helpers (duck-typed against the committed question channel)
# --------------------------------------------------------------------------- #


def _question_id(question: Any) -> Any:
    """Return the question's event id, or the question itself when unknown."""
    payload = getattr(question, "payload", None)
    if isinstance(payload, dict) and "event_id" in payload:
        return payload["event_id"]
    return question


def _question_text(question: Any) -> str:
    """Return the human-readable question text."""
    payload = getattr(question, "payload", None)
    if isinstance(payload, dict) and "question" in payload:
        return str(payload["question"])
    return str(question)


# --------------------------------------------------------------------------- #
# Operator
# --------------------------------------------------------------------------- #


class Operator:
    """The root door between the human and the agent mesh (INFO-017).

    Parameters are duck-typed so tests and the CLI can inject fakes:

    * ``runtime`` — anything with ``spawn(requirement, driver=...)`` and
      ``await_(agent_id)`` (the committed :class:`~dhc.runtime.Runtime`).
    * ``question_channel`` — anything with ``pending_questions()`` and
      ``answer(question_event_id, answer)`` (the committed communication
      module's channel).
    * ``stream`` — anything with ``write(str)`` and ``flush()``; defaults to
      ``sys.stdout``.
    * ``messenger`` — optional duck-typed ``send(sender_id, recipient_id,
      body)`` used to deliver mid-turn steering messages to a running agent.
    * ``input_fn`` — callable returning one line of operator input; defaults
      to ``input`` (never used by tests).
    * ``chunk_size`` — streaming chunk size in characters.
    """

    def __init__(
        self,
        runtime: Any,
        question_channel: Any = None,
        stream: Any = None,
        messenger: Any = None,
        input_fn: Optional[Callable[[str], str]] = None,
        chunk_size: int = 80,
    ) -> None:
        self.runtime = runtime
        self.question_channel = question_channel
        self.stream = stream if stream is not None else sys.stdout
        self.messenger = messenger
        self.input_fn = input_fn if input_fn is not None else input
        self.chunk_size = chunk_size
        #: Steering messages that could not be delivered (documented no-op
        #: fallback when no messenger is injected).
        self.undelivered_steers: list[tuple[str, str]] = []

    # -- root door -----------------------------------------------------------

    def run(
        self,
        requirement: str,
        driver: Optional[Callable[[Any], Optional[str]]] = None,
    ) -> Result:
        """Start a root agent for *requirement* and drive it to settlement.

        Spawns the root through the runtime, then blocks until it settles
        (continuous chat, INFO-022). Returns the root's settled
        :class:`~dhc.models.Result`.

        *driver* is the pluggable brain: called with the Agent, it returns the
        next code block to execute, or ``None`` to settle. When omitted, the
        deterministic :class:`DefaultDriver` is used so the operator works
        without an API key.
        """
        if driver is None:
            driver = DefaultDriver()
        handle = self.runtime.spawn(requirement=requirement, driver=driver)
        is_settled = getattr(self.runtime, "is_settled", None)
        if callable(is_settled) and self.question_channel is not None:
            # Answer operator questions MID-RUN (INFO-023): poll for
            # settlement instead of blocking in await_, sweeping the
            # question channel each pass so a question asked mid-turn
            # reaches the human before the run settles. The asking agent
            # reads the answer as an event on its own stream (0015).
            while not is_settled(handle.id):
                self.answer_questions(loop=False)
                time.sleep(0.05)
        completion = self.runtime.await_(handle.id)
        # Final sweep: late questions (asked after settlement) still get
        # answered; the answer event lands on the asker's stream.
        self.answer_questions(loop=False)
        return Result(
            done=True,
            ok=completion.status.value == "completed",
            value=completion.summary,
            reason=completion.reason,
            artifacts=list(completion.artifact_ids),
        )

    # -- mid-turn steering (INFO-022) ---------------------------------------

    def steer(self, agent_id: str, message: str) -> bool:
        """Inject *message* into a running agent's context (mid-turn steering).

        Delivery rides the framework's directed-message primitive
        (``runtime.send("operator", agent_id, message)``, decision 0015)
        when the runtime provides it — the message lands on the agent's
        own event stream. Fallbacks: the injected duck-typed ``messenger``
        (``send(sender_id, recipient_id, body)``), else a documented no-op
        recorded on :attr:`undelivered_steers` — the operator never raises
        on steering.

        Returns ``True`` when the message was actually delivered (via the
        runtime or the messenger) and ``False`` when it was only recorded
        as undelivered — callers must not report a no-op as a success
        (F8: ``!steer`` used to print "steered <id>" either way).
        """
        send = getattr(self.runtime, "send", None)
        if callable(send):
            try:
                send("operator", agent_id, message)
                return True
            except Exception:  # noqa: BLE001 - steering never raises
                pass
        if self.messenger is not None:
            self.messenger.send(
                sender_id="operator", recipient_id=agent_id, body=message
            )
            return True
        self.undelivered_steers.append((agent_id, message))
        return False

    # -- read-only inspection (D2) ------------------------------------------

    def inspect(self, agent_id: str) -> dict:
        """Return a read-only window into a live agent's workspace (D2).

        Returns a copy of the agent's workspace globals (via the runtime's
        ReplEngine when available) plus a status/result/caps digest. Never
        mutates anything — no inject/advance/kill. Duck-typed: when the
        runtime/engine lacks ``globals_for``, a minimal view (status +
        result) is returned instead — never raises.
        """
        view: dict = {"agent_id": agent_id}
        try:
            view["status"] = self.runtime.status(agent_id).value
        except Exception:  # noqa: BLE001 - inspection is best-effort
            view["status"] = None
        try:
            result = self.runtime.result(agent_id)
            view["result"] = {
                "done": result.done,
                "ok": result.ok,
                "value": result.value,
                "reason": result.reason,
                "artifacts": list(result.artifacts),
            }
        except Exception:  # noqa: BLE001 - inspection is best-effort
            view["result"] = None
        engine = getattr(self.runtime, "repl_engine", None) or getattr(
            self.runtime, "engine", None
        )
        globals_for = getattr(engine, "globals_for", None)
        if callable(globals_for):
            try:
                view["workspace"] = dict(globals_for(agent_id))
            except Exception:  # noqa: BLE001 - inspection is best-effort
                view["workspace"] = {}
        else:
            view["workspace"] = {}
        # Caps digest: the visible ceiling-caps view (D2), read-only.
        try:
            caps_fn = view["workspace"].get("caps")
            view["caps"] = caps_fn() if callable(caps_fn) else None
        except Exception:  # noqa: BLE001 - inspection is best-effort
            view["caps"] = None
        return view

    # -- operator questions (INFO-023) --------------------------------------

    def answer_questions(self, loop: bool = True) -> None:
        """Poll the question channel and answer pending operator questions.

        For each pending question the question is printed to the stream, an
        answer is read from :attr:`input_fn`, and
        ``question_channel.answer(question_event_id, answer)`` is called.
        When *loop* is true the poll continues until no questions remain
        pending (a single sweep); when false only one question is answered
        per call.
        """
        if self.question_channel is None:
            return
        while True:
            pending = self.question_channel.pending_questions()
            if not pending:
                return
            question = pending[0]
            self.stream.write(f"[operator] {_question_text(question)}\n")
            self.stream.flush()
            answer = self.input_fn("answer> ")
            self.question_channel.answer(_question_id(question), answer)
            if not loop:
                return

    # -- streaming responses (INFO-022) -------------------------------------

    def stream_response(self, text: str) -> None:
        """Write *text* to the stream in chunks, flushing after each chunk.

        *chunk_size* is configurable at construction (default 80 chars) so
        tests can assert chunk boundaries cheaply.
        """
        for i in range(0, len(text), self.chunk_size):
            self.stream.write(text[i : i + self.chunk_size])
            self.stream.flush()


# --------------------------------------------------------------------------- #
# ChatSession
# --------------------------------------------------------------------------- #


class ChatSession:
    """Continuous chat loop between the operator and the human (INFO-022).

    ``start()`` reads lines from ``input_fn`` and dispatches each one through
    :meth:`start_one`:

    * ``!quit`` — exit the loop.
    * ``!steer <agent_id> <msg>`` — mid-turn steering via ``operator.steer``.
    * ``!inspect <agent_id>`` — read-only workspace view via ``operator.inspect``.
    * anything else — a new requirement run through ``operator.run(...)``.

    The in-loop commands are advertised in :attr:`COMMANDS` (the CLI banner
    renders them, W6.3) so the operator never has to guess the vocabulary.

    This is the interactive surface the CLI drives; tests inject a scripted
    ``input_fn`` and a fake output stream.
    """

    #: The in-loop commands, in banner order: (command, one-line help).
    #: Single source of truth for the chat banner (W6.3) — the CLI renders
    #: these lines verbatim, so the banner can never drift from the
    #: dispatch in :meth:`start_one`.
    COMMANDS: tuple[tuple[str, str], ...] = (
        ("!quit", "exit the chat"),
        ("!steer <agent_id> <message>", "steer a running agent mid-turn"),
        ("!inspect <agent_id>", "read-only workspace view of an agent"),
    )

    def __init__(
        self,
        operator: Operator,
        input_fn: Callable[[str], str],
        output_stream: Any,
        driver: Optional[Callable[[Any], Optional[str]]] = None,
        on_result: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.operator = operator
        self.input_fn = input_fn
        self.output_stream = output_stream
        self.driver = driver
        #: Optional sink receiving each settled result's text (used by the
        #: CLI to mirror responses into the transcript file).
        self.on_result = on_result
        #: Whether the echo-mode banner has been printed yet (printed once,
        #: on the first requirement line, when the DefaultDriver fallback is
        #: in use — i.e. ``driver is None``).
        self._echo_banner_shown = False

    def start(self) -> None:
        """Run the chat loop until ``!quit`` (or the input is exhausted)."""
        while True:
            line = self.input_fn("> ")
            if line is None:
                return
            if not self.start_one(line):
                return

    def start_one(self, line: str) -> bool:
        """Process a single chat line; return False when the loop must exit."""
        line = line.strip()
        if not line:
            return True
        if line == "!quit":
            return False
        if line.startswith("!steer "):
            parts = line.split(maxsplit=2)
            if len(parts) < 3:
                self.output_stream.write("usage: !steer <agent_id> <message>\n")
                self.output_stream.flush()
                return True
            _, agent_id, message = parts
            delivered = self.operator.steer(agent_id, message)
            if delivered:
                self.output_stream.write(f"steered {agent_id}\n")
            else:
                # F8 honesty: the message was only recorded on the
                # operator (no messenger wired) — say so, loudly.
                self.output_stream.write(
                    f"steer NOT delivered to {agent_id} (no messenger wired)\n"
                )
            self.output_stream.flush()
            return True
        if line.startswith("!inspect "):
            parts = line.split(maxsplit=1)
            if len(parts) < 2:
                self.output_stream.write("usage: !inspect <agent_id>\n")
                self.output_stream.flush()
                return True
            agent_id = parts[1].strip()
            view = self.operator.inspect(agent_id)
            if view.get("status") is None:
                # F8 honesty: an unknown id must be named, not rendered as
                # a blank "status: None" view.
                known = len(
                    getattr(self.operator.runtime, "_agents", None) or {}
                )
                self.output_stream.write(
                    f"unknown agent id: {agent_id} ({known} agents known)\n"
                )
                self.output_stream.flush()
                return True
            self.output_stream.write(f"inspect {agent_id}\n")
            self.output_stream.write(f"  status: {view.get('status')}\n")
            self.output_stream.write(f"  result: {view.get('result')}\n")
            self.output_stream.write(f"  caps: {view.get('caps')}\n")
            self.output_stream.write(
                f"  workspace keys: {sorted(view.get('workspace', {}))}\n"
            )
            self.output_stream.flush()
            return True
        if not self._echo_banner_shown and self.driver is None:
            # Echo honesty (decision D3): the DefaultDriver fallback echoes
            # the requirement back — say so once, and point at the real-LLM
            # entry point. The two-entry-point split is a recorded design
            # decision (INFO-070); dhc chat never calls an LLM.
            self.output_stream.write(
                'echo mode: no LLM driver wired — set OPENAI_API_KEY and use '
                '"python3 -m dhc.ui.terminal" for the real driver\n'
            )
            self.output_stream.flush()
            self._echo_banner_shown = True
        result = self.operator.run(line, driver=self.driver)
        text = result.value if result.ok else result.reason
        self.output_stream.write(f"{text}\n")
        self.output_stream.flush()
        if self.on_result is not None:
            self.on_result(text)
        return True