### DEPRICATED ###

---
id: INFO-043
type: info
title: Recommended minimal harness contract
summary: The entire model stays small — call_code, delegate, await, status, cancel — with four concepts (REPL state, call, task, event) and five events (CALL, DELEGATE, COMPLETE, AWAIT, CALLBACK), enough to answer what was asked, returned, spawned, and observed
date: 2026-10-06
status: draft
---

# Recommended minimal harness contract

> Incorporated 2026-10-06 from the harness use-case source analysis (`INFO-037`) — the recommended contract is organizing design, not a use case.

The entire model can remain surprisingly small:

```python
# Stateful execution
call_code(code)

# Asynchronous execution
task = delegate(task, inputs=None, on_done=None)

# Synchronization
result = await task

# Non-blocking observation
task.status()
task.done()

# Optional control
task.cancel()
```

With four fundamental concepts:

```text
REPL state
    persistent computational workspace

Call
    synchronous black-box execution boundary

Task
    asynchronous child execution

Event
    externally observable lifecycle transition
```

And the trace consists primarily of:

```text
CALL
  input → output

DELEGATE
  task → input

COMPLETE
  task → output

AWAIT
  task → synchronization point

CALLBACK
  task → callback execution
```

The most important architectural property is that **the harness understands the lifecycle and boundaries, but not the internals of the code being executed**.

That gives the agent a very large action space while retaining enough structure to answer:

1. What did the agent ask the runtime to do?
2. What did the runtime return?
3. What child work was spawned?
4. Which parent spawned it?
5. When did it complete or fail?
6. When did the parent observe/synchronize on it?
7. Which state and results were available at each point?

That is enough to build a powerful agent harness without turning the harness into an instrumented programming-language runtime.

## Owns
- The recommended minimal contract: the primitive set, the four-concept model, and the event vocabulary.

## Excludes
- The design model it distills — `INFO-042`.
- The commitment to the contract — `INFO-037`.
