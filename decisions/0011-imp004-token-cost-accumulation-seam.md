---
id: 0011
type: decision
title: "IMP-004 — Token/cost accumulation at the driver seam: one write, one read, zeros on the mock path"
date: 2026-10-08
status: accepted
---

# Token/cost accumulation at the driver seam — the inert `AgentNode` usage fields get a single provenance

## Context

IMP-004 (`breakdown/06-evolution/selected/inert-token-and-cost-fields-on-the-agent-state-view-model.md`)
documents the hazard: `AgentNode` (`src/dhc/agent/state.py:78-95`) carries
`tokens`, `messages`, `context_tokens`, `prompt_tokens`, `completion_tokens`,
`cached_tokens`, `cost_usd`, and `cum_cost_usd` — all defaulting to zero — and
**no code path ever assigns them**. The state view-model therefore "lies by
default": `AgentNode.usage` renders nothing, so an operator inspecting a live
agent (the `operator.inspect` window, IMP-001 D2) sees no usage at all, and any
future budget or rot policy that wants a token signal has no signal to read.

The data already exists at the driver boundary. `LLMResponse`
(`src/dhc/llm/llm.py:93-100`) carries `usage` (a dict with
`prompt_tokens`/`completion_tokens`/`cached_tokens`, built at
`llm.py:355-370`) and `cost_usd` (estimated at `llm.py:348`). The provider call
already measures what the view-model claims to report; the value is simply
dropped on the way to the agent's state.

The drop happens at a specific seam. `LLMClient.generate_code_block`
(`llm.py`) calls `self._provider.generate(...)` — which returns the full
`LLMResponse` with `usage`/`cost_usd` — and then returns only
`_strip_markdown_fences(response.text)`. The usage is discarded at that line.
`LLMDriver.__call__` (`src/dhc/llm/driver.py`) is the one place that holds both
the `agent` (the live object in `runtime._agents`) and the `client`
(`self._client`), so it is the natural accumulation point.

The mock path must stay zero. `MockDriver` (the default fabrication brain, D4)
and `MockLLM` return no usage; the propagation must be None-safe so the
default loop's behavior is unchanged and the mock path reports zeros, not a
crash and not a fabricated number.

## Decision

**Accumulate usage at the driver seam, with one write and one read.**

1. **The client records the last response's usage.** `LLMClient` (and
   `MockLLM`, for interface parity) stores the most recent
   `LLMResponse.usage` / `LLMResponse.cost_usd` on itself
   (`_last_usage` / `_last_cost`) after each `generate_code_block` call.
   `MockLLM` leaves them `None` — it never fabricates usage.

2. **The driver is the ONE write seam.** `LLMDriver.__call__` reads
   `self._client._last_usage` / `_last_cost` after a successful
   `generate_code_block` and, when usage is present, calls
   `agent.record_usage(usage, cost_usd)`. This is the single place where
   provider usage flows into agent state. `MockDriver` never calls
   `record_usage` (it has no client), so the mock path writes nothing.

3. **`Agent.record_usage` is the ONE accumulation point on the agent.**
   It adds `prompt_tokens`/`completion_tokens`/`cached_tokens` into
   per-agent accumulators and adds `cost_usd` into a running total. It is
   None-safe: a `None` usage or a missing key contributes nothing. The
   agent is a live object in `runtime._agents`, so the accumulators are
   exactly what the view-model reads.

4. **`build_agent_tree` is the ONE read seam.** It copies the agent's
   accumulated `prompt_tokens`/`completion_tokens`/`cached_tokens`/
   `cost_usd` (and `tokens = prompt + completion`) into the `AgentNode`
   view-model. `build_stats` then aggregates those node values into the
   `Stats` counters, so `stats.json` reports real totals.

The zero-cost mock path reports zeros: `MockDriver`/`MockLLM` never set
`_last_usage`, so `record_usage` is never called, the accumulators stay at
their zero defaults, and `AgentNode`/`Stats` render zeros (and `usage`
renders the empty string, as before).

## Rationale

1. **One provenance, by construction.** The IMP-004 leaf demands "one
   accumulation point … so the view-model's numbers have a single
   provenance." Writing at the driver seam (the only place holding both the
   agent and the client) and reading at `build_agent_tree` (the only place
   that builds the view-model) means there is exactly one writer and one
   reader. A double-count would require a second writer, which the design
   does not provide; the cumulative test (exact sum across N calls) pins it.
2. **The driver seam is where the data and the agent already meet.**
   `LLMDriver.__call__(agent)` receives the live `Agent` and owns
   `self._client`. No new object, no new thread, no new event is needed —
   the usage is read off the client that just produced it and written onto
   the agent that just consumed the block. This is the minimal change that
   connects the two.
3. **None-safety keeps the mock path byte-identical.** `MockDriver` has no
   client and `MockLLM` sets no usage, so the accumulation is a no-op on the
   default path. The existing 483-test suite (which exercises the mock path
   pervasively) is the proof: it stays green with no test weakened.
4. **The view-model is unchanged in shape.** `AgentNode` already has the
   fields; `build_agent_tree` already builds the node. We only populate the
   fields from the agent's accumulators. No new field, no new file, no new
   public API on the view-model.

## Alternatives Considered

- **(b) Accumulate in `LLMClient.generate_code_block` itself.** Rejected: the
  client does not hold the `agent` — it only sees the prompt. It would need a
  back-reference to the agent, coupling the LLM layer to the agent layer and
  creating a second, less-obvious write path. The driver already holds both.
- **(c) Accumulate in the pump loop (`loop.py`) after `driver(agent)`.**
  Rejected: the pump calls `driver(agent)` and only sees the returned `str`
  (or `None`) — the usage is not in the return value, so the pump would have
  to reach into the client/driver internals, scattering the read across the
  loop. The driver is the tighter seam.
- **(d) Emit a usage event and have `StateWriter` accumulate it.** Rejected:
  it adds an event kind, a bus subscription, and a second accumulation site
  (the writer), violating "one accumulation point" and coupling the
  view-model to the event stream for a value that is already on the agent.
- **(e) Store usage on the `LLMResponse` and thread it through the driver's
  return value.** Rejected: it changes the driver's `-> str | None` contract
  (a public, tested surface) to `-> (str, usage) | None`, a larger blast
  radius than reading an attribute off the client the driver already owns.

## Changes made

- `src/dhc/llm/llm.py` — `LLMClient` and `MockLLM` record
  `_last_usage`/`_last_cost` after each `generate_code_block` (the client
  from the real provider; `MockLLM` leaves them `None`).
- `src/dhc/llm/driver.py` — `LLMDriver.__call__` reads the client's
  `_last_usage`/`_last_cost` and calls `agent.record_usage(...)` when usage
  is present (the ONE write seam).
- `src/dhc/agent/agent.py` — `Agent` gains `record_usage(usage, cost_usd)`
  plus the accumulators it writes (`_prompt_tokens`, `_completion_tokens`,
  `_cached_tokens`, `_cost_usd`) and the read properties
  (`prompt_tokens`, `completion_tokens`, `cached_tokens`, `tokens`,
  `cost_usd`).
- `src/dhc/agent/state.py` — `build_agent_tree` copies the agent's
  accumulated usage into the `AgentNode` (the ONE read seam); `build_stats`
  aggregates the node values into `Stats`.
- `tests/agent/test_token_cost.py` — new: usage-propagation tests (a
  spy/mock client returning usage populates the node and accumulates across
  calls; a no-usage call leaves it zero; the mock path reports zeros;
  `agents.txt`/`stats.json` report real values after an LLM-driven run).

## Verification

Full suite green in a single run: **492 passed** (483 baseline + 9 new),
no test weakened. New tests in `tests/agent/test_token_cost.py`:

1. `test_record_usage_accumulates` — two calls with usage sum exactly
   (no double count); a `None`-usage call adds nothing.
2. `test_driver_writes_usage_to_agent` — a spy client returning a usage
   dict drives `LLMDriver.__call__`; the agent's `prompt_tokens`/
   `completion_tokens`/`cost_usd` are non-zero and cumulative.
3. `test_no_usage_leaves_agent_zero` — a client with no usage leaves the
   agent's fields at zero (no crash, no fabricated number).
4. `test_mock_path_reports_zeros` — `MockDriver`/`MockLLM` run to
   settlement; `build_agent_tree`/`build_stats` report zeros and
   `AgentNode.usage` renders the empty string.
5. `test_agents_txt_and_stats_report_real_values` — an LLM-driven run
   (spy client with usage) through the pump; `agents.txt` shows the token
   figures and `stats.json` shows the aggregated totals.

## Consequences

- Operators now see real token/cost figures in `agents.txt` and `stats.json`
  after LLM-driven runs; the `operator.inspect` window (IMP-001 D2) has a
  token signal to read.
- `cost_usd` is a **provider estimate** (`llm.py:384-387`), not a billing
  figure; the view-model reports it as such.
- The mock path is unchanged: zeros, no crash, no fabricated number.
- **Open (deferred, per the IMP-004 leaf):** whether `messages` (also inert)
  is populated from the same seam, and whether `context_tokens` should be
  derived from the digest size (`agent/context.py`, `DIGEST_KEEP`) or left to
  the provider's `prompt_tokens`. Both are out of scope here; the seam is
  shaped so either can be added without a second write path.
