---
id: INFO-057
type: info
title: Quick start
summary: Install and run — mock path, real LLM path, and the end-to-end value demonstration
date: 2026-10-09
status: current
---

# Quick start

- Install: `pip install -e .`.
- Mock path, no API key: `dhc --mock` — minimal chat TUI, deterministic mock driver.
- Real LLM path: `export OPENAI_API_KEY=sk-...` then `dhc` — real LLM driver (gpt-4o by default).

## Value demonstration

- Run: `python3 examples/value_demo.py`.
- Runs a complete end-to-end session on the fully-wired runtime: the root
  publishes, fans out to 3 children, one child fails, the parent aggregates,
  then settles.
- Writes a structured report to
  `.dynamic-harness/261006_230325_4a23/artifacts/value_demo_report.md`.
- The report answers what value dhc provides during agent work:
  - one coded action replaces N tool-call turns;
  - progressive disclosure saves context;
  - crash containment keeps siblings alive;
  - at-most-once settlement prevents duplicate work;
  - parent liveness holds until children settle.
- If `OPENAI_API_KEY` is set, one real-LLM turn is also run to prove the real
  path.

## Owns
- How the runtime is installed, started, and demonstrated: the quick start and the value demonstration.

## Excludes
- How claims are checked — `INFO-056`.
- What the wired runtime is composed of — `INFO-058`.
