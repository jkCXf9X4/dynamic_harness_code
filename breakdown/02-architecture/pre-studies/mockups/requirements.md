# Mockups: requirements

What each sketch must show, with citations — the contract the mockups read
against (see `_support.py`). Trivial bodies are deliberate: the shape is the
annotation. These mockups are centered on the **code-as-action space** — the
in-code surface an agent turns program against — and exist to verify that
surface, not to design it.

## Conventions every sketch follows

- **One turn = one Python block** (`INFO-002`). Each sketch is a block the
  runtime would persist and execute against the agent's persistent REPL.
- **Only the `_support.py` surface is reachable.** No stream draining, no
  polling of a stream, no harness plumbing — the remainder is ordinary Python.
- **Sketch globals stand in for REPL variables.** State that would live in the
  agent's workspace between actions is written as module globals, with the
  turn boundary marked in comments.
- **Every sketch closes a small V** (`INFO-003`): analyze the allocated
  requirement, implement, verify against the parent's acceptance, report.

## Sketches

| Sketch | Must show | Citations |
| --- | --- | --- |
| `mock_single_turn.py` | One self-verifying turn as a single Python block: analyze → implement (tools, search, tail read) → verify against acceptance → publish → return summary + artifact IDs | `INFO-002`, `INFO-003`, `INFO-006` |
| `mock_batch_loop.py` | One expressive block replacing N tool-call turns: a loop over inputs with transforms, selective failure handling, and one aggregated report | `INFO-001`, `INFO-002`, `INFO-003` |
| `mock_delegation_fan_out.py` | Decomposition by writing delegation code: spawn encapsulated children with explicit context, register completion callbacks by held spawn handle, settled values arrive as data between the parent's actions, children return summary + artifact IDs, parent pulls detail on demand | `INFO-004`, `INFO-030`, `INFO-045`, `INFO-006` |
| `mock_persistent_repl_tools.py` | The REPL as the agent's workspace: expensive intermediates computed once and reused, agent-developed tools loaded into the workspace, reused by later actions without recompute | `INFO-030`, `INFO-007` |

Each sketch runs end-to-end via `run_mockups.py`, which drives every block
against `_support.py` and asserts the `Result`/`Artifact` shapes hold.