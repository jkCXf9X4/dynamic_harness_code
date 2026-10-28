---
id: IMP-032
type: imp
title: Per-agent process isolation
summary: Run each agent in its own supervised OS process so cancellation kills, CPU is capped per agent, and settlement stays parent-side
date: 2026-10-27
status: current
---

# Per-agent process isolation

## Why — pain and evidence

- A blocked turn thread cannot be killed (`src/dhc/framework/repl.py:499-511`).
- The abandoned thread keeps the runtime, store, bus, and facade live (`pump.py:309-322`).
- No mutating boundary checks settlement, so a dead agent can still publish, send, and spawn.
- `bash` survives a step timeout and runs to its own 30 s deadline (`agent.py:108-119`).
- One spinning turn pins one core indefinitely; GIL slices degrade every peer.
- Measured: one leaked spinner slows a later test file 13x, two spinners 18-37x.
- Seven tests leak a true `while True: pass`, and the full suite takes 22 min against 7:30 in parts.
- CPU caps are impossible in-process; `RLIMIT_CPU` is per process, so threads cannot carry one.
- Containment claims in `INFO-005` and the D5 gate hold only at the workspace dict today.

## The proposed shape

- One OS process per agent, started as a session leader.
- The child owns its REPL namespace and its agent-authored loop.
- The parent keeps supervision: settlement, hard gates, completion log, message routing.
- Transport is a unix socket per agent; measured round trip is 16-34 us.
- Runtime-mutating tools become parent-side RPC calls; pure helpers stay in the child.
- `AgentBackend` seam carries advance, kill, cancel, snapshot, and namespace injection.
- The in-process thread backend stays as the default until the process backend passes its contract suite.
- Children are forked from a preloaded forkserver, not spawned cold.

## What must change

- Pump coupling: 22 engine calls in `pump.py:338-719` become backend operations.
- Namespace: 53 bound names per turn become child-local helpers plus RPC stubs.
- `globals_for` becomes a debug snapshot RPC, not a live dict.
- Operator question handling stops invoking a workspace closure (`tooling/operator.py:249`).
- Event delivery and completion callbacks become data messages, not inline closures.
- Caps read reported usage per step; wall clock, steps, children, and messages stay parent-side.
- `RLIMIT_CPU` and `RLIMIT_AS` are set in the child; SIGXCPU maps to a failed settlement.
- Benchmark and UI read a supervised proxy instead of `runtime._agents`.
- 30 test files touch internals; a contract suite must run against both backends.

## Containment

- Cancellation sends SIGTERM, then SIGKILL after the grace window; the whole process group dies.
- The group includes `bash` children, so no workload outlives the agent.
- A crash or signal maps to a failed settlement with the signal named in the reason.
- Settlement stays parent-side, so at-most-once survives a child crash.
- Process isolation is not a sandbox: files stay shared until filesystem confinement lands.

## Costs, measured

- Cold spawn with the package imported: 545 ms median, 46 MB RSS.
- `multiprocessing.Pipe` round trip: 34 us median at 32 bytes.
- Unix socket round trip: 16 us median at 32 bytes.
- Pickle rejects lambdas, file handles, and locks, so REPL state cannot migrate.
- Child process memory sets the practical ceiling on agent fan-out.
- Estimated effort: 8 to 10 weeks for one developer, high risk.

## Risks and open questions

- Forkserver preload latency is unmeasured; it decides whether deep hierarchies are affordable.
- Fork after threads exist is unsafe; the runtime must fork from a single-threaded preload point.
- 43 tests inject live objects through `spawn(namespace=...)`; the process backend cannot accept them.
- Debuggability drops: two stacks, transported tracebacks, harder breakpoints.
- Event ordering must stay per-agent FIFO across a socket boundary.
- Platform start methods differ; Linux is the only initial target.

## Acceptance criteria

- A `while True: pass` turn is killed within the grace window plus 250 ms, and no process survives.
- No side effect is possible after settlement, including publish, send, and spawn.
- A CPU limit trip settles failed with the signal named.
- 727 existing tests stay green on the in-process backend.
- The contract suite passes on the process backend with at-most-once delivery and replay.
- Spawn and round-trip numbers are recorded on the target machine before defaulting.

## Owns

- The process-isolation candidate: supervision model, backend seam, kill semantics, and measured costs.

## Excludes

- The thread backend and its current behaviour — `INFO-038`.
- The control split and gate ownership — `INFO-053`.
- The agent-owned loop and REPL — `INFO-037`, `INFO-050`.
- Event durability and at-most-once — `INFO-048`, `INFO-051`.
- The containment gap that motivates this — `IMP-001` decision records.
- Mechanism of the final implementation — the `02-architecture` leaf this candidate creates.
