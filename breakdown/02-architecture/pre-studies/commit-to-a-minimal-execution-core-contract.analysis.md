# Harness Use Cases

Guidelines not rules when it comes to code 

> Incorporated 2026-10-06 as the source analysis for `INFO-030` … `INFO-037`.

The design model and the recommended minimal contract live one layer up in Architecture (`INFO-042`, `INFO-043`) — they are organizing design, not use cases.

# 2. REPL Use Cases

## UC-REPL-01 — Persist variables across calls

**Goal:** Allow the agent to perform multi-step computation without repeatedly reconstructing state.

### Interaction

```python
df = load_data()
clean_df = clean(df)
```

Later:

```python
summary = clean_df.groupby("country").size()
```

The second call executes against the same REPL state.

### Harness requirement

The REPL state must persist across `call-code` invocations within an agent run.

### Important property

The harness does not need to trace the creation or mutation of individual variables.

The trace only needs to capture:

```text
call 1
  input → code
  output → result

call 2
  input → code
  output → result
```

The persistence of `clean_df` is a runtime semantic, not a tracing concern.

---

## UC-REPL-02 — Reuse expensive computation

**Goal:** Prevent the agent from having to repeat expensive work.

```python
embedding = compute_embeddings(dataset)
```

Later:

```python
nearest = search(embedding, query)
```

The agent can retain large intermediate objects in the REPL.

### Harness requirement

State remains available until the run ends, is explicitly reset, or reaches a configured resource boundary.

---

## UC-REPL-03 — Persist agent-generated knowledge

The REPL can serve as short-lived working memory.

```python
research_notes = {}
research_notes["approach_a"] = ...
```

Later:

```python
compare(research_notes)
```

This allows the agent to progressively construct an internal workspace.

---

## UC-REPL-04 — Inspect previous outputs

Outputs can be retained separately from arbitrary REPL state.

For example:

```python
outputs()
outputs[-3:]
```

This allows the agent to recover information it previously generated without requiring every intermediate value to remain in a named variable.

### Design distinction

Separate:

```text
REPL state
    variables / functions / objects

Output history
    explicitly returned or emitted results
```

This avoids treating every variable assignment as an externally meaningful output.

---

## UC-REPL-05 — Branch or checkpoint REPL state

A long-running agent may benefit from state identity:

```text
S1 → call 1 → S2 → call 2 → S3
```

The harness can optionally checkpoint or identify states.

This enables:

* recovery after failure
* debugging
* branching
* resuming a run
* comparing alternative execution paths

The trace need only retain the state identifiers if full state snapshots are stored separately.

---

# 3. Traceability Use Cases

## UC-TRACE-01 — Trace every `call-code` boundary

For every invocation:

```text
call_id
run_id
input
output
status
```

Example:

```json
{
  "call_id": "c42",
  "input": {
    "code": "x = expensive_computation(); emit(x)"
  },
  "output": {
    "result": "..."
  },
  "status": "completed"
}
```

### Requirement

The harness must be able to reconstruct:

> What did the agent send to the code runtime, and what did the runtime return?

---

## UC-TRACE-02 — Do not instrument arbitrary code

The agent should be free to execute arbitrary code.

The harness does **not** need to record:

* individual Python operations
* variable assignments
* function calls
* filesystem accesses
* network calls
* intermediate values
* internal reasoning

unless they are explicitly part of the `call-code` output.

This keeps the action space unconstrained while keeping the trace manageable.

---

## UC-TRACE-03 — Trace large inputs and outputs by reference

Large REPL objects should not necessarily be copied into the trace.

Instead:

```text
call input
    content hash
    object/artifact reference

call output
    content hash
    object/artifact reference
```

The trace establishes what crossed the boundary while a separate artifact store holds the payload.

---

## UC-TRACE-04 — Establish causal ordering

Every call receives a unique ID and ordering information.

Example:

```text
c41
  ↓
c42
  ↓
c43
```

For concurrent work, the trace becomes a DAG rather than a simple sequence:

```text
             c42
            /   \
          t1     t2
          │       │
          ▼       ▼
        result  result
            \   /
             c51
```

This makes concurrent execution reconstructable.

---

## UC-TRACE-05 — Trace delegation

Starting child work creates a delegation event:

```text
delegate
    task_id
    parent_run_id
    parent_call_id
    task_input
```

Completion creates:

```text
complete
    task_id
    output
    status
```

The child's internal execution remains opaque.

---

## UC-TRACE-06 — Trace failures

Failures should be first-class outputs.

```json
{
  "task_id": "t17",
  "status": "failed",
  "error": {
    "type": "Timeout",
    "message": "..."
  }
}
```

The harness should distinguish:

```text
completed
failed
cancelled
timeout
```

rather than treating all non-successful executions as generic errors.

---

# 4. Child Synchronization Use Cases

## UC-SYNC-01 — Fire and continue

The agent starts work and immediately continues.

```python
a = delegate("Research approach A")

do_other_work()
```

### Semantics

`delegate()` is non-blocking.

The parent does not wait for the child.

### Use case

Parallelize independent research or computation.

---

## UC-SYNC-02 — Explicit await

The agent starts asynchronous work, continues independently, then synchronizes when the result becomes necessary.

```python
a = delegate("Research A")

local_result = do_local_work()

a_result = await a
combine(local_result, a_result)
```

### Semantics

`await` blocks the current execution until the child reaches a terminal state.

This is the basic **fork/join** pattern.

---

## UC-SYNC-03 — Poll without blocking

The agent checks whether work is complete without waiting.

```python
if a.done():
    result = a.result()
else:
    continue_work()
```

Or:

```python
a.status()
```

Possible states:

```text
pending
running
completed
failed
cancelled
```

### Use case

The agent can make opportunistic use of results without introducing synchronization points.

---

## UC-SYNC-04 — Completion callback

The agent delegates work and asks to be notified when it finishes.

```python
def research_done(task):
    findings.append(task.result)

delegate(
    "Research approach A",
    on_done=research_done
)

continue_work()
```

The parent continues while the child runs.

When the child finishes, the callback is scheduled into the parent REPL.

### Important semantic property

The callback does not execute concurrently against the parent interpreter.

Instead:

```text
child completes
      ↓
completion event
      ↓
parent callback queue
      ↓
callback executes in parent REPL
```

This avoids concurrent mutation of the parent REPL.

---

## UC-SYNC-05 — Callback on failure

Callbacks should run for both successful and unsuccessful completion.

```python
def done(task):
    if task.status == "completed":
        integrate(task.result)
    else:
        handle_failure(task.error)
```

This avoids requiring a separate callback mechanism for errors.

---

## UC-SYNC-06 — Multiple children with independent callbacks

```python
def done(task):
    results[task.id] = task.result

a = delegate("Research A", on_done=done)
b = delegate("Research B", on_done=done)
c = delegate("Research C", on_done=done)

continue_work()
```

Each child completes independently.

The parent receives completion notifications as they become available.

---

## UC-SYNC-07 — Fan-out / fan-in

The agent launches several children and later waits for all of them.

```python
tasks = [
    delegate("Analyze A"),
    delegate("Analyze B"),
    delegate("Analyze C")
]

results = [await t for t in tasks]
synthesize(results)
```

Conceptually:

```text
             parent
          /    |    \
         A     B     C
          \    |    /
           synchronize
                |
             synthesize
```

This is likely to be one of the most important real-world patterns.

---

## UC-SYNC-08 — Mixed callback and await

The agent can use callbacks for opportunistic processing while retaining the ability to explicitly synchronize.

```python
a = delegate("Research A", on_done=store_result)
b = delegate("Research B", on_done=store_result)

do_other_work()

await a
use_results()
```

The callback may already have processed `b` before the parent explicitly awaits it.

`await` therefore means:

> Ensure this task has reached a terminal state.

It does not imply that the result has not already been observed.

---

# 5. Child REPL Isolation

## UC-REPL-CHILD-01 — Child gets its own REPL

Each delegated task receives an independent mutable execution environment.

```text
Parent REPL
     │
     ├── delegate A → Child A REPL
     │
     └── delegate B → Child B REPL
```

Child A's variables must not accidentally collide with Child B's or the parent's variables.

---

## UC-REPL-CHILD-02 — Explicit context transfer

The parent can provide inputs to a child:

```python
delegate(
    "Analyze this dataset",
    inputs={"dataset": df}
)
```

The child receives a defined input context rather than implicitly sharing the parent's mutable namespace.

This makes delegation semantics substantially easier to reason about.

---

## UC-REPL-CHILD-03 — Return results, not mutable state

A child returns an output:

```python
result = await task
```

rather than automatically merging its REPL into the parent.

If the parent wants a child-produced artifact or value, it explicitly retains it.

This preserves isolation while allowing arbitrary collaboration.

---

# 6. Nested Delegation

## UC-NEST-01 — Child delegates to another child

A child should itself be able to delegate.

```text
Parent
   │
   └── Child A
         ├── Child B
         └── Child C
```

The harness therefore represents delegation as a task tree/DAG rather than assuming a flat collection of workers.

Each task should have:

```text
task_id
parent_task_id
parent_call_id
```

This allows complete causal reconstruction.

---

# 7. Cancellation

## UC-CANCEL-01 — Cancel unnecessary child

```python
a.cancel()
```

Example:

```text
delegate A
delegate B

A produces sufficient answer

cancel(B)
```

The task transitions to:

```text
cancelled
```

and its completion event records the cancellation outcome.

