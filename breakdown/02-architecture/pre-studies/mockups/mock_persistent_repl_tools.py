"""INFO-030 · INFO-007 — the REPL is the agent's workspace.

Two actions in the same agent, separated by the turn boundary marked in the
comments. What the first action builds stays live in the workspace: an
expensive intermediate computed once, and an agent-developed tool — a plain
Python callable the agent wrote itself — loaded into its own REPL. The second
action reuses both. No recompute, no harness-provided infra, nothing shared
implicitly across agents.
"""

from __future__ import annotations

from _support import Agent, Result

# --- agent REPL state (module globals stand in for the workspace) --------
_index: dict[str, list[str]] = {}
_recall = None  # the agent-developed tool, once defined


def first_action(agent: Agent, corpus: tuple[str, ...] = ("hello", "dynamo")) -> Result:
    # Expensive intermediate: computed once, kept live across actions.
    words = " ".join(corpus).lower().split()
    for w in set(words):
        _index.setdefault(w, []).append(w)

    # Agent-developed tool: plain Python the agent authored, lived in the REPL.
    def recall(query: str, k: int = 3) -> list[str]:
        return sorted((t for t in _index if query in t), reverse=True)[:k]

    global _recall
    _recall = recall
    return agent.complete("corpus indexed; recall() ready in this workspace")


def next_action(agent: Agent, query: str = "hell") -> Result:
    # Reuse: the loaded tool and the live index, with zero recompute.
    assert _recall is not None, "this agent's workspace should still hold recall()"
    tops = _recall(query)

    report = agent.publish(headline=f"recall for {query!r}",
                           summary=f"{len(tops)} hit(s) from live workspace",
                           report=tops)
    return agent.complete(f"answered {query!r} without recompute",
                          artifacts=(report,))


def turn(agent: Agent) -> Result:
    first_action(agent)
    # --- turn boundary: the runtime persists each block separately --------
    return next_action(agent)


if __name__ == "__main__":
    a = Agent(requirement="index the corpus, then answer recalls")
    print(turn(a))