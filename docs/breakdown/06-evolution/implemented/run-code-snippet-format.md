---
id: IMP-031
type: imp
title: run_code snippet format
summary: run_block accepts only def call(self, spec) payloads, validated and invoked with the agent facade; exec_block is the raw runner path
date: 2026-10-14
status: current
---

# run_code snippet format

`run_block` is the run_code surface: the agent-facing path for synthesized code. Payloads are `def call(self, spec)` snippets. One format governs all agent-side code — the delegation snippet (`namespace=` idiom) uses the same shape.

## Format

- Payload defines exactly one module-level `def call(self, spec)`.
- First parameter named `self`. Optional second parameter named `spec`.
- Sync function. No further parameters, no `*args`/`**kwargs`, no keyword-only.
- Supporting module-level statements allowed: imports, helper defs.
- A duplicate `def call`, a wrong parameter name, extra parameters, `async def`, or a syntax error is rejected.

## Enforcement

- AST check runs before any exec. A rejected payload never executes.
- Rejection is a failed `Result`; the reason names the violation (error-as-value, `INFO-020`).
- A validation failure leaves the workspace untouched.

## Invocation

- The payload execs against the agent's persistent workspace, then `run_block` invokes `call(agent, spec)`.
- The receiver is the facade the namespace binds as `agent`, captured before the exec. A payload cannot redirect it.
- Arity decides the call: one parameter gets `call(agent)`; two get `call(agent, spec)`.
- The entrypoint return value becomes `res.value`. A `None` return falls back to the raw exec `Result`.
- Exceptions from the invocation are contained as failed `Result`s (`INFO-005`).

## Sharing contract

- `spec` in. Return value out. `state` persists across run_code calls.
- Payload locals stay function-scoped. They never leak into the workspace.
- Module-level names the payload defines (`call`, helpers) are workspace citizens.

## The split

- `exec_block` is the raw nested exec. The default `__runner__` routes driver-produced blocks (MockDriver scripts, LLM output) through it. No format requirements.
- `ReplEngine.run_block` stays format-free. The engine never validates.
- Both citizens refresh the namespace before each exec (`inject_nolock`).
- `exec_block` is a guarded citizen: `FABRICATION_NAMES`, `ensure_fabrication` re-seed, surface registry tier internal.
- Driver block format is untouched: the doctrine prompt and MockDriver scripts stay flat.

## Known edge

- A resumed workspace holding an old `__runner__` source that calls `ctx["run_block"]` with driver blocks hits validation. Accepted pre-1.0.

## Verification

- `tests/framework/test_subagent_setup.py`: format enforcement, sharing contract, fan-out via `spec`, failure probing.
- `tests/tooling/test_fabrication.py`: the default loop runs flat driver blocks through `exec_block`.

## Owns
- The run_code payload format contract: `def call(self, spec)` enforced on `run_block`.
- The `run_block` / `exec_block` split and the default `__runner__`'s use of `exec_block`.

## Excludes
- Engine-level nested exec semantics — `ReplEngine.run_block` (`IMP-001`).
- The delegation snippet via `namespace=` — no kit citizen; pinned by `tests/framework/test_subagent_setup.py`.
- Driver block format — the doctrine prompt, `MockDriver` scripts.
