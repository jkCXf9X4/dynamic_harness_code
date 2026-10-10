---
id: INFO-064
type: info
title: The driver seam
summary: How decide gets its answer — the swappable driver, workspace-swappable prompt assembly, provider calls with retry and timeout containment, and usage recording at the seam
date: 2026-10-10
status: current
---

# The driver seam

Decide gets its answer through a swappable driver. The seam spans kit factory, prompt assembly, provider call, usage recording.

## The seam

- The kit factory `make_decide` births decide (`tooling/fabrication.py`).
- Decide resolves its brain as `state.get("_driver", driver)`, falling back to the closure driver.
- `_turns`/`_calls` bookkeeping lives in workspace state, not driver attributes.
- The pump seeds `state["_driver"]` before kit install — spawn-time scripted drivers work (`framework/pump.py`).
- An agent swaps its brain by replacing `state["_driver"]`; the state dict survives namespace refresh.
- `wiring.py` injects `MockDriver` and `driver_from_settings` into every namespace.
- `MockDriver` is deterministic — script blocks returned in order, then None.
- `driver_from_settings`: `mock=True` or no API key returns `MockDriver(DEFAULT_SCRIPT)`.
- Otherwise it returns an `LLMDriver` over an `LLMClient` built from `settings.provider`.
- Provider and SDK client construct lazily — no key, no network at build time.

## LLMDriver

- `__call__(agent) -> str | None` returns the next code block, None to settle.
- Turn cap `max_turns=20`: at cap returns None.
- Client failure sets `_failed_once`, returns a `fail(...)` code block; next call settles.
- Empty or blank block returns None; no usage recorded on that settle.
- A wired rot detector scores each produced block: `rot_detector.observe(code)`.
- Report stashed on `agent._last_rot_report` — the pump tripwire's rendezvous (`INFO-021`).
- Observe-only: the block returns unchanged.

## Prompt assembly

- `LLMDriver._build_prompt` assembles the prompt (`llm/driver.py`).
- Resolution order: workspace `build_prompt` name, then `state["build_prompt"]` slot, then `default_build_prompt`.
- The state slot survives the per-turn namespace refresh; the workspace name does not.
- An override is called as `build_prompt(agent, driver)` and must return the prompt string.
- `default_build_prompt` ships as kit citizen `build_prompt` — replacing it changes the LLM's prompt.
- Recent context: last 5 events via `runtime.events(agent.id)`, payload JSON capped at 200 chars.
- `llm/prompts.py` structured composition is superseded and unwired (`INFO-066`).

## Provider layer

- `LLMClient` wraps the sole concrete `OpenAIProvider` over the sync `openai.OpenAI` SDK (`llm/llm.py`).
- Each call sends `_SYSTEM_PROMPT` plus the assembled prompt as user content; markdown fences stripped from the response.
- Config defaults: model `deepseek/deepseek-v4-flash`, base_url `https://openrouter.ai/api/v1`.
- OpenRouter routing `extra_body` sent only when base_url contains "openrouter".
- Retry budgets by failure class: `max_retries=4` generic transients, `rate_limit_max_attempts=6` rate limits.
- Backoff is exponential in the class retry count, times 3.0 for rate limits.
- Every retry sleep is capped at 30 s; jitter adds up to 0.5 s.
- SDK client is built with `max_retries=0` — dhc owns retries.
- A watchdog thread bounds every call by `timeout`; a hang raises `TurnTimeoutError`, never retried.
- Final failure raises `TurnError` (`INFO-020` owns the survival promise).

## Usage recording

- Provider extracts prompt_tokens, completion_tokens, cached_tokens, and cost; per-mtok prices give a USD estimate.
- The client records `_last_usage` and `_last_cost` on itself after each call.
- The driver reads both, calls `agent.record_usage(usage, cost)` — the one write seam, only when a block was produced.
- `MockLLM` never fabricates usage — the seam writes nothing on the mock path.

## Owns
- How decide gets its answer: swappable driver, prompt assembly resolution, provider call behavior, usage recording at the seam.

## Excludes
- Rot detection semantics — `INFO-021`.
- LLM-call timeout survival promise — `INFO-020`.
- Usage read into the state view — `INFO-059`.
- Fabrication kit contract — `INFO-037`.
- Unwired modules detail — `INFO-066`.
