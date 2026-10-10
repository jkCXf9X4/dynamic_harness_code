---
id: INFO-070
type: info
title: The two entry points
summary: The two CLI surfaces — the dhc chat command on a bare runtime and the operator terminal on a wired runtime — and what each constructs
date: 2026-10-10
status: current
---

# The two entry points

Two CLI surfaces ship. The `dhc` console script runs a bare runtime; the operator terminal runs the wired one.

## The dhc chat command

- Console script `dhc = "dhc.cli:main"` (`pyproject.toml`); implementation `src/dhc/cli.py`.
- Constructs bare `Runtime(settings=settings)` directly; never calls `build_runtime`.
- Bare form runs the legacy loop: no caps watchdog, no rot gate (`INFO-055`, `IMD-004`).
- Adds `Operator` plus `ChatSession` (`src/dhc/ui/operator.py`); all chat semantics live there.
- Prints one banner: rich rule when available, plain text fallback.
- Flags: `--context`, `--transcript`, `--mock`, `--model`, `--inspect`.
- Persists `.dhc/context.md` plus `.dhc/transcript.md` under the workspace root (`INFO-028`).
  - Every input line appends to both files, then runs as one requirement.
- `--inspect AGENT_ID` prints a read-only view: status, result, caps, workspace keys; exits 0.
- In-loop commands: `!quit` exits, `!steer <agent_id> <msg>` steers, `!inspect <agent_id>` inspects.
- EOF exits the loop.
- `ChatSession` receives driver `None`; `Operator.run` falls back to `DefaultDriver`.
- `DefaultDriver` settles each requirement with one coded `complete(requirement)` action.
- `--mock`, `--model`, and key presence select the banner text only.
- The chat command never calls an LLM.

## The operator terminal

- Implementation `src/dhc/ui/terminal.py`; invocation `python3 -m dhc.ui.terminal`.
- No `dhc.terminal` module exists; the docstring's `python3 -m dhc.terminal` does not resolve.
- Constructs the wired runtime: `build_runtime(settings, mock, artifact_root=settings.artifact_root)`.
- Attaches `StateWriter` at the artifact root's parent and subscribes it to the bus.
- Prefers the wired `runtime.operator`, so `ask_operator` questions reach the human (`INFO-023`).
- Flags: `--requirement`, `--batch`, `--mock`, `--config`, `--model`, `--base-url`, `--api-key`.
- `--requirement TEXT` or `--batch` runs batch mode once: outcome, aggregate, state-file paths; returns 0.
- Interactive mode keeps one root agent across turns.
- No continuation hook exists, so each requirement spawns a fresh root agent.
- Slash commands: `/tree`, `/agents`, `/artifacts [id]`, `/events`, `/stats`, `/resume <agent_id>`, `/compact`, `/help`, `/quit`.
- Ctrl+C cancels the running agent and returns to the prompt.
- EOF exits.
- `--config PATH` loads an explicit `harness.json` as the highest-precedence layer.
- `--model`, `--base-url`, `--api-key` override the provider config on the settings.

## Owns
- The two CLI surfaces: what each is, what each constructs, what each offers.

## Excludes
- Install and quick start: `INFO-057`.
- Runtime composition behind `build_runtime`: `INFO-058`.
- Where run output lands and how to read it: `INFO-071`.
- Hosting and embedding use cases: `INFO-008`, `INFO-025`.
