# examples/

Runnable demonstrations of the dhc runtime.

## value_demo.py

End-to-end agent session with hard evidence. Runs a fully-wired runtime
(real modules, `MockDriver` — deterministic, no API key needed) through a
complete session:

- root requirement → a coded action publishes a plan artifact
- spawns 3 children (fan-out); children publish artifacts, one child FAILS
  (crash containment)
- parent awaits children, aggregates artifact ids, completes; runtime settles

It then writes a structured value report answering "what value does dhc
provide during agent work?": one coded action replacing N tool-call turns,
progressive disclosure (headline → summary → report) saving context, crash
containment keeping siblings alive, at-most-once settlement preventing
duplicate work, and parent liveness until children settle. If
`OPENAI_API_KEY` is set, one real-LLM turn is also run (LLMDriver over
LLMClient) to prove the real path; otherwise the mock path is used.

Run from the repo root (any machine — no API key, no installation needed):

```bash
python3 examples/value_demo.py
```

Exit code 0 on success. The script puts `src/` (the package) and the repo
root (for the shared `examples._mock_scripts` helper) on `sys.path`, so it
runs from a source checkout without installation. The value report is written
to a fresh per-run temp artifact root (the path is printed at the end of the
run) — no machine-specific paths.
