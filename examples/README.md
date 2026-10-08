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

Run from the repo root:

```bash
.venv/bin/python examples/value_demo.py
```

Exit code 0 on success. The script inserts the repo root into `sys.path`, so
it runs from a source checkout without installation. The report is written to
the hardcoded `REPORT_PATH` under `.dynamic-harness/` (see the file header).
