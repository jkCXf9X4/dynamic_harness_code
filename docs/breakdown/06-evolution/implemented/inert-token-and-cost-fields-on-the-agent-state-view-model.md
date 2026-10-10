---
id: IMP-004
type: imp
title: Inert token and cost fields on the agent state view-model
summary: AgentNode's token and cost fields are never populated. State view-model reports zero usage; the provider call already returns usage
date: 2026-10-08
status: current
pb_exempt: true
---

# Inert token and cost fields on the agent state view-model

Scoped candidate, not implementation approval. Needs decision record and task contract before code changes begin (change pipeline).

## Why — pain and evidence

- **The fields exist but are never written.**
  - `src/dhc/ui/state.py` (`AgentNode`, lines 78–95) carries `tokens`, `messages`, `context_tokens`, `prompt_tokens`, `completion_tokens`, `cached_tokens`, `cost_usd`, and `cum_cost_usd`.
  - All default to zero.
  - Scoping brief (run `261008_105638_6a18`, §2) and decision record `IMD-001` (agent module separation) list them as inert.
  - No code path in `src/dhc/framework/` or `src/dhc/wiring.py` ever assigns them.

- **The data already exists at the driver boundary.**
  - `LLMResponse` (`src/dhc/llm/llm.py:93–100`) carries `usage`: a dict with `prompt_tokens`/`completion_tokens`/`cached_tokens`, built at `llm.py:355–370`.
  - It also carries `cost_usd` (estimated at `llm.py:348`).
  - The provider call already measures what the view-model claims to report.
  - The value is simply dropped on the way to the agent's state.

- **The view-model lies by default.**
  - `AgentNode.usage` (state.py:112–128) renders token/cost figures only when non-zero.
  - Today it renders nothing.
  - An operator inspecting a live agent (the `operator.inspect` window, IMP-001 D2) sees no usage at all.
  - Any future budget or rot policy that wants a token signal has no signal to read.

## The proposed shape

- **Propagate usage from the driver to the agent state.**
  - Driver call returns an `LLMResponse` with `usage`/`cost_usd`: the agent's state accumulates it.
  - Per-call `prompt_tokens`/`completion_tokens`/`cached_tokens` and a running `cost_usd`/`cum_cost_usd`.
  - `AgentNode` then reflects the agent's real consumption.

- **One accumulation point.**
  - Accumulation lives in one place: the driver-call seam in the loop or the fabrication kit's `decide`.
  - Not scattered across consumers.
  - The view-model's numbers then have a single provenance.

- **A test that a provider call with usage populates the node.**
  - `MockDriver`/`_SpyClient` returns a usage dict.
  - Assert the node's `prompt_tokens`/`completion_tokens`/`cost_usd` are non-zero and cumulative across calls.

## What must change

- `src/dhc/framework/pump.py` (or the `decide` seam in `fabrication.py`)
  - Accumulate `LLMResponse.usage`/`cost_usd` into the agent's state on each driver call.
- `src/dhc/ui/state.py`
  - `AgentNode` reads the accumulated values. No new fields needed; the fields already exist.
- `tests/` (state/loop tests)
  - Usage-propagation test: a call with usage populates the node.
  - A call without usage leaves it zero.

## Containment

- **Usage is double-counted (accumulated at two seams).**
  - The cumulative test asserts the exact sum across N calls.
  - A double count fails it.
- **A provider returns no usage.**
  - The no-usage test asserts the node stays zero.
  - No crash, no fabricated number.

## Risks and open questions

- **MockDriver has no usage.**
  - Default fabrication path (D4) uses `MockDriver`, which returns no usage.
  - Propagation must be None-safe so the default loop's behavior is unchanged.

- **Cost estimation is provider-specific.**
  - `cost_usd` is an estimate (`llm.py:384–387`).
  - The view-model should report it as an estimate, not a billing figure.

- **Open.**
  - Whether `messages` (also inert) is populated from the same seam: open.
  - Whether `context_tokens` should derive from the digest size (`agent/context.py`, `DIGEST_KEEP`) or is left to the provider's `prompt_tokens`: open.

## Owns

- **Inert token/cost fields hazard.**
  - The unpopulated `AgentNode` usage fields.
  - The propagation of `LLMResponse.usage`/`cost_usd` into the agent's state.

## Excludes

- Rot-detection *policy* (what to do with a token signal), `INFO-021` on adoption, not this candidate.
- The `_MemoryBus` drain race, sequenced follow-on to decision record `IMD-001`, not this candidate.
- Stringly-typed event kinds (IMP-002), wall-clock base mix (IMP-003).
