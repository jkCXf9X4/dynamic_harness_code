---
id: INFO-056
type: info
title: Running the tests
summary: How the suite is run — pytest commands, the deterministic MockDriver, and where the detail lives
date: 2026-10-09
status: current
---

# Running the tests

- Full suite (unit + integration), from the repo root: `python3 -m pytest -q`.
- End-to-end wiring only: `python3 -m pytest tests/test_integration.py -q`.
- The integration tests use the deterministic `MockDriver` — no network, no API key.
- Suite layout, filing rule, and the current baseline live in `tests/README.md`.

## Owns
- How the runtime's claims are checked by the suite: the commands, the deterministic driver, and where the detail lives.

## Excludes
- The thing under test — the module map (`INFO-055`).
- Routine build and run steps — `INFO-057`.
