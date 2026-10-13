# dhc Interface Review — Ease of Use & Simplicity

**Date:** 2026-10-12
**Scope:** every interface a human or LLM touches — the embedder API (`dhc/framework/`, `dhc/wiring.py`), the in-block agent API (`dhc/tooling/`), the prompt layer (`dhc/llm/`), the operator UX (`dhc/cli.py`, `dhc/ui/`), configuration, and onboarding materials (README, examples, docs).
**Method:** full read of the interface-bearing modules, spot-verification of the highest-severity claims, and evaluation against one question: *how many concepts must a user hold in mind, and how many ways are there to get it wrong?*

---

## 1. Executive summary

dhc's **core ideas are genuinely good** — one-turn-one-block, a persistent REPL, delegation by code, content-addressed progressive-disclosure artifacts, and at-most-once settlement are a coherent and attractive design. The **minimal happy path is real**: `build_runtime(mock=True)` → `spawn` → `await_` in four calls, and `spawn` / `await_` / `read_artifact` in three lines of agent code.

But around that kernel, the interface has accreted **four parallel surfaces for nearly every concept**, no single source of truth for the API that matters most (what the LLM sees), and an onboarding path that does not deliver what it advertises. The single most serious finding is that **the prompts and the code teach three different APIs, and the only prompt actually wired into the runtime is incomplete — it omits `read_artifact`, the read half of the framework's flagship feature.** An LLM following any of the shipped documentation verbatim will raise `NameError` or `TypeError`.

The pattern behind most findings: dhc evolves by **addition without consolidation**. New mechanisms (pump, channels, caps, fabrication kit) are layered on top of old ones (legacy loop, `Settings`, `send`), and the cost of the duplication is paid by every user, in every prompt, on every turn.

**Severity overview**

| # | Finding | Severity | Layer |
|---|---------|----------|-------|
| 1 | Prompt/API vocabulary drift — 3 prompts, 3 different APIs; the wired one omits `read_artifact` | **Critical** | Prompt |
| 2 | No single source of truth for the agent namespace (4 registration sites, ~49 names) | **Critical** | Agent API |
| 3 | `messenger.read(message_id)` is unusable — `Message` has no id field | High | Agent API |
| 4 | Quick start is an echo bot; README's real-LLM claim is false; README links are dead | High | Onboarding |
| 5 | Flagship demo crashes on any machine but the author's (hardcoded absolute path) | High | Onboarding |
| 6 | 4 ways to await, 2 ways to send, 3 names for a room topic, 3 settle implementations | High | Agent API |
| 7 | `complete(artifacts=...)` takes ids, not Artifact objects; magic strings; silent aliases | Medium | Agent API |
| 8 | Silent no-ops (`!steer`, `/resume`, `channel_read` unknown room, `archive` fallback) | Medium | Operator UX |
| 9 | Config split-brain: legacy `Settings`/`DHC_*` env vs pydantic `HarnessConfig`, ad-hoc merges, 11 alias keys | Medium | Embedder |
| 10 | `build_runtime` attaches 13 undeclared attributes; wiring by reassigning private methods | Medium | Embedder |

---

## 2. Prompt layer — the API the LLM actually sees (Critical)

This is where "ease of use" matters most, because the primary user of the agent API is an LLM whose only documentation is the system prompt.

**What is wired:** the live prompt is `default_build_prompt` (`src/dhc/llm/driver.py:82-118`). Its *entire* API documentation is the 8-line `_SURFACE_DOC` string (`driver.py:38-47`), hand-maintained, one signature per function, no semantics, no examples.

**What is wrong:**

1. **`_SURFACE_DOC` omits `read_artifact`.** It lists `publish` but not the read half of the artifact store. Progressive disclosure (`headline → summary → report`, README:30-33) is the framework's headline feature, and the wired prompt gives the LLM no way to discover how to pull a child's result. It also omits `read_artifact`, `list_artifacts`, `archive`, `post`, `channel_read`, `list_tools`, `caps`, and the entire fabrication kit.
2. **`agent_system_prompt.txt` (103 lines, `src/dhc/llm/`) is loaded and tested but never wired** — `driver.py` does not import it. And it teaches a wrong API anyway: `escalate(reason)` (line 27) where the real binding is `escalate(requirement, reason)` — an LLM following it raises `TypeError`; plus `converse(child_id)`, `report()`, `plan(steps=...)`, `prune`/`compress`, none of which exist as tools.
3. **`ORCHESTRATOR_SYSTEM_PROMPT` (`src/dhc/llm/prompts.py:60-82`) teaches `delegate`, `converse`, `report`, `ask`, `read_artifact(child's agent_id...)`** — a completely different, nonexistent API. It is marked superseded but still shipped.
4. **Prose compensating for API footguns.** The unwired prompts are full of "Only call `report()` after cleanup is complete", "DISK BEFORE REPORT", "Never blindly delegate the same target twice" — order-of-operations rules that exist because the API doesn't enforce them structurally. The wired prompt, ironically, is too thin to convey any of this; the LLM gets neither guard rails nor documentation.

**Verdict:** three prompts, three APIs, none correct. This is the highest-leverage defect in the codebase: it makes the framework's most important interface — the one its LLM agents code against every turn — partially undocumented and partly misdocumented.

**Fix direction:** generate `_SURFACE_DOC` from the actually-registered namespace (the registrations already exist at 4 sites; a registry could drive both the prompt and `list_tools`), delete or wire the stale prompts, and make the arity of every listed function match its binding.

---

## 3. The in-block agent API (High)

### 3.1 What's good

- Minimal delegation is genuinely clean:

  ```python
  h = spawn("analyze the logs")
  c = await_(h)                     # -> Completion
  read_artifact(c.artifact_ids[0])  # progressive disclosure
  ```

- `publish(headline, summary, report)` with three tiers is a good shape — one call, no ordering choices.
- Crash containment and the `failed` terminal state mean failure handling is a normal `if`, not a rescue protocol.

### 3.2 Surface sprawl

- The injected namespace is **~49 names assembled from 4 independent registration sites** (`Runtime._build_namespace` `runtime.py:462-501`; wiring `wiring.py:182-220`; plus fabrication kit names `fabrication.py:530-552`). No module lists the full surface. `AGENT_SURFACE` (`agent.py:355-387`) lists 24 facade names; `FABRICATION_NAMES` guards 10 of 15 kit names ("harmless extras", `fabrication.py:546`). The only complete enumeration is a docstring sentence.
- **Four ways to await**: `await_(h)` (blocking function), `yield Await(h)` (parking object), `h.await_()` (method), and `Sleep`. Poll has the same triple: `poll(h)`, `yield Poll(h)`, `h.poll()`. Each pair has subtly different semantics (blocking vs cooperative vs facade), and nothing tells the LLM which idiom to prefer.
- **Two ways to send**: `send(recipient_id, body)` and `messenger.send(recipient_id, body)` — the second documented as "sugar" for the first (`channel_tools.py:80-94`).
- **Three names for a room topic**: `room(name)`, `post(room_name, body)`, `channel_read(topic)` (`channel_tools.py:187-193`).
- Escalation and operator questions **return raw `Event` objects**; the answer must be excavated from the consume-once `events()` cursor. The counterpart methods (`EscalationChannel.ack`, `OperatorQuestionChannel.answer`) exist (`channels.py:255,321,351`) but are not registered as block tools — a parent cannot ack an escalation from a block at all.

### 3.3 Concrete footguns

- **`messenger.read(message_id)` is unusable**: `Message` has no `id` field (`models.py:270-278` — `sender_id`, `recipient_id`, `body`, `ts`), and `messenger.inbox()` returns id-less messages. The ids exist only in event payloads. The documented read-state API cannot work from its own inbox.
- **`complete(headline, artifacts=())` takes ids, not artifacts** (`models.py:140-149` documents "artifact *ids* (by reference)"). Publishing, capturing `art.id`, and passing `[art.id]` is an unenforced order-of-operations dance; passing the `Artifact` object itself fails validation.
- **Magic strings with hidden aliases**: `read_artifact(id, level=...)` accepts `"full"` and `"raw"` silently (`artifact_tools.py:88`) while its error message claims only `headline|summary|report` (`artifact_tools.py:94`).
- **Side-effectful reads**: `room(name)` joins as a side effect and returns a deep-copy snapshot — the polling idiom is "join again to see newer traffic" (`channel_tools.py:106-118`).
- **Silent failures**: `channel_read` on an unknown room returns `[]` (`channels.py:188`); `archive()` silently falls back to returning the id (`artifact_tools.py:109-112`); `rollback()` with no checkpoints returns `False` (`fabrication.py:315-317`).
- **`spawn(..., **kwargs)` swallows typos** (`agent.py:207-208`) — a misspelled `namespce=` is accepted and ignored.
- **No fan-out combinator**: parallel work is N spawns + N awaits, with selective failure handling done by hand against the `AgentStatus` enum. There is no `gather(..., return_exceptions=)` equivalent. Counting the concepts a verified delegation requires (~12: requirement, acceptance, handle, driver, status enum, Completion, Result envelope, artifact ids, tiers, level strings...) — the API is a concept zoo relative to the 3-line happy path.
- **Structured reports make a JSON round-trip**: the `report` tier returns `object`, is JSON-dumped to a string for the agent (`artifact_tools.py:89-92`), and the agent re-parses it.

---

## 4. The embedder API (Medium-High)

### 4.1 What's good

`build_runtime(settings, mock, artifact_root)` (`wiring.py:228-232`) is a real composition root, documented as "the ONLY place the operator tooling is instantiated". It hides ~14 of ~20 classes a hand-wiring would need. The bare `Runtime()` with in-memory defaults is usable standalone for tests.

### 4.2 The costs

- **13 undeclared attributes attached post-construction** (`wiring.py:291-315`): `runtime.messenger`, `.rooms`, `.dispatcher`, `.boundary_log`, `.artifact_store_real`, `.rot_detector`, … never appear in `Runtime`'s class body — invisible to type-checkers, undiscoverable in an IDE, and the demo must read `rt.artifact_store_real` (`value_demo.py:160-165`), an unexplained `_real` suffix.
- **Wiring by private-method reassignment**: `runtime._build_namespace = build  # type: ignore[method-assign]` at three registration sites (`wiring.py:225`, `framework_tools.py:150`, `channel_tools.py:236`, `artifact_tools.py:180`), each wrapping the previous — layering order is a silent contract. Tests reach into `rt._agents`, `rt._stop_flags`, `rt._caps_watchdog` routinely; the public API is not sufficient for testing the framework.
- **API that lies**: `ReplEngine.run_block(..., timeout=None)` documents the timeout as "not enforced" (`repl.py:238-247`); `spawn()` silently auto-starts an un-started runtime, making `start()` decorative (`runtime.py:280-282`); `status()` is literally `return self.poll(agent_id)` (`runtime.py:656-658`); `Agent.cancel()` only records a last result while `Runtime.cancel()` actually cancels — same verb, two behaviors across the boundary.
- **Two invisible execution engines**: `legacy_loop` vs `pump_loop` chosen by `supports_pump()` (`pump.py:145-148`) — which loop runs depends on whether the engine has `.advance`, and the settle path differs between them (three settle implementations: `Runtime._settle`, `make_settle`/`make_settle_completed`, inline in `legacy_loop`).
- **`spawn`'s 7 parameters include `_agent_callback`** (`runtime.py:255-264`) — an underscore-prefixed *public* parameter that silently switches `on_done` between two callback models.
- **Error discipline is inconsistent**: unknown agent ids raise bare `KeyError` from six Runtime methods (`runtime.py:626-685`) while unknown message recipients raise `ChannelError` — 8 defined `DhcError` subclasses, applied unevenly.
- **Duplicated machinery**: four near-identical cap predicates (`cap_hit`, `caps_exceeded`, `Runtime._caps_hit`, `_caps_watchdog`); three read cursors over the same event stream; two bus contracts bridged by `_WiredBus`.

### 4.3 Configuration split-brain

Two parallel configuration systems coexist: the legacy `Settings` dataclass driven by `DHC_*` env vars (`config.py:228-239,271-292`) and the pydantic `HarnessConfig` from `harness.json` (`config.py:140-146`), merged ad hoc in `read_cap` (`caps.py:31-45`) and again in `Settings.provider`. Symptomatic aliasing: **11 alias keys map onto 5 caps** (`caps.py:74-86`), `max_agents` vs `max_children` vs `children`; four names for a time ceiling (`timeout_seconds`, `wall_clock`, `max_turn_seconds`, `_DEFAULT_TIMEOUT_SECONDS`). `harness.json.example` omits 3 of the 8 `safety` keys. On the plus side: **every config key has a default** — no file is required, and the XDG → cwd → `--config` layering is well documented.

---

## 5. Operator & onboarding UX (High)

- **The advertised quick start is an echo bot.** `dhc` chat constructs `ChatSession(driver=None)` (`cli.py:146`) and `Operator.run` falls back to `DefaultDriver`, which returns `complete(requirement)` — the user's line echoed back (`operator.py:58-65`). README:45-46 claims `export OPENAI_API_KEY=...` then `dhc` yields "real LLM driver, gpt-4o by default" — false; the docs admit the key only "selects the banner text" (`docs/breakdown/05-operation/the-two-entry-points.md:27-30`). The real entry point is `python3 -m dhc.ui.terminal`, while `terminal.py`'s own docstring (line 19) says `python3 -m dhc.terminal` — which does not resolve.
- **All root-README navigation links are dead**: they point at `breakdown/00-intent/` etc., but the tree lives at `docs/breakdown/` (verified: no `breakdown/` at root).
- **The flagship demo cannot complete on a clean clone**: `examples/value_demo.py:51-54` hardcodes `REPORT_PATH = Path("/home/eriro/pwa/2_work/...")`; line 359 then mkdirs under that prefix. `examples/README.md:31-32` acknowledges the wart without fixing it. Of the demo's 365 lines, only ~50 exercise the framework; ~120 are hand-rolled markdown report building; the mock scripts are near-verbatim copies of `tests/test_integration.py`.
- **Two CLIs, two vocabularies**: chat uses `!quit`, `!steer`, `!inspect` (the latter two absent from the banner); terminal uses `/tree`, `/agents`, `/artifacts`, `/events`, `/stats`, `/resume`, `/compact`, `/help`, `/quit`, plus bare `quit`/`exit`. `!steer` in chat is a **documented silent no-op** that prints "steered <id>" anyway (no messenger is wired in the chat path; `operator.py:177-200,346`). `/resume` finds nothing by default because `build_runtime` attaches no checkpoint store.
- **Docs are an architecture record, not a tutorial**: 86 files under `docs/breakdown/` navigated by `INFO-xxx`/`AD-`/`IMD-` citation ids. Genuinely precise, but there is no getting-started tutorial and **no API reference at all for the in-block agent surface** — the single most-used interface in the product. The best onboarding material in the repo is `tests/test_integration.py` (215 lines, readable fixture, full sessions) — a test file is doing the job of the docs.
- **Concept load**: a first meaningful run requires understanding ~28 terms (requirement, settlement, the three drivers, two entry points, two exit vocabularies, `acceptance=()` conventions, artifact tiers, `DHC_*` vs harness.json, block vs REPL, …). That is a lot of ceremony for an echo bot.

---

## 6. What is genuinely good (keep and protect)

1. **`build_runtime` + `MockDriver`** — a 4-call deterministic boot with no API key. The mock scripting story is one of the strongest features in the repo; it is why the tests can be this good.
2. **Content-addressed artifacts with three tiers** — immutable, deduplicated on write, and progressive disclosure is a genuinely elegant answer to context-budget management. The *design* is excellent; only the read-path ergonomics (id juggling, JSON round-trip) need work.
3. **Strong invariants**: at-most-once settlement, crash containment, terminal-state discipline, causal event ids. These simplify reasoning about failure, which is rare in agent frameworks.
4. **The test suite as documentation** — 34 files, 394 passing, with readable end-to-end sessions. `tests/test_integration.py` and `tests/ui/test_terminal.py` are the actual quick-start material.
5. **Self-aware documentation** — warts are honestly recorded (e.g., the terminal-module-path and `/resume` issues are admitted in docs). Recording them is good; the gap is that recording has substituted for fixing.

---

## 7. Root causes

1. **No single source of truth for the agent surface.** Four registration sites, hand-copied prompt strings, a `list_tools()` that lists less than what is injected. Every divergence between them is a bug the LLM steps on at runtime.
2. **Additive evolution without consolidation.** Legacy loop + pump; `Settings` + `HarnessConfig`; `send` + `messenger`; three settles; four cap predicates; two CLI vocabularies. Each addition was locally reasonable; the sum is a combinatorial tax on users.
3. **Prompts as a band-aid for API roughness.** Where the API permits misuse (report-before-disk, ids-not-objects, join-to-poll), the fix has been a prose rule in a prompt rather than a structural constraint — and the prose itself then drifted out of sync with the code.
4. **Docs written for auditors, not users.** The `INFO-xxx` record is thorough about *why*; nothing answers *"what do I type next?"*.

---

## 8. Recommendations (prioritized)

**P0 — make the advertised experience true (days, not weeks)**
1. Generate `_SURFACE_DOC` (or the whole system prompt's API section) from the registered namespace at composition time; include `read_artifact`. One registry should drive the prompt, `list_tools`, and the docs.
2. Reconcile the three prompts: wire one correct system prompt, fix `escalate`'s arity in it, and delete the superseded `ORCHESTRATOR_SYSTEM_PROMPT` and any prompt teaching `delegate`/`converse`/`report`.
3. Fix `value_demo.py` (derive `REPORT_PATH` from the runtime's artifact root), repair the README's `breakdown/` links, and make `dhc` with `OPENAI_API_KEY` set either run the real driver or state plainly that chat is echo-only.

**P1 — collapse the duplicated surface**
4. Pick **one** await idiom and one poll idiom for prompts and docs (recommend the function forms `await_`/`poll` plus the `Await`/`Poll` yield forms for cooperative contexts); deprecate the rest.
5. Merge `send`/`messenger.send`; unify `name`/`room_name`/`topic`.
6. Fix or remove `messenger.read` (add `Message.id`, or accept the `Message` object); expose `ack`/`answer` as block tools or stop returning raw `Event` objects from `escalate`/`ask_operator`.
7. Let `complete(artifacts=...)` accept `Artifact` objects as well as ids; make `read_artifact`'s level aliases either official or rejected.

**P2 — make silence loud and structure typed**
8. Replace bare `KeyError` on unknown agents with a `DhcError` subclass; make `!steer`, `channel_read` on unknown rooms, and `archive` fallbacks report instead of returning empty/sentinel values.
9. Declare `build_runtime`'s decorations as typed attributes (or a `WiredRuntime` subclass); replace private-method reassignment with an explicit chain-of-responsibility registration.
10. Unify configuration behind `HarnessConfig` (generate `harness.json.example` from the model; bridge `DHC_*` env vars in one place); unify the two CLIs' command vocabulary and document in-loop commands in the banner.
11. Write the missing quick-start around the `tests/test_integration.py` fixture pattern, and a one-page API reference for the in-block surface generated from the same registry as (1).

---

## 9. Bottom line

dhc is one good 3-line API wearing four coats. The kernel — `build_runtime` → `spawn` → `await_`, and `spawn` → `await_` → `read_artifact` — is simple, sound, and demonstrably testable. Every problem found in this review lives in the layers added around that kernel: a prompt layer that documents APIs that don't exist while omitting the one that does, an agent surface assembled from four sites with three vocabularies, an embedder surface whose composition is done by monkey-patching privates, and an onboarding path that advertises an LLM and delivers an echo. None of these are architectural failures — the invariants are right — but they are exactly the kind of friction that decides whether an agent framework is adopted or abandoned. The P0 list alone would transform first-contact quality; P1 would halve the concept count.

---

# Remediation status (2026-10)

> Appended after the remediation waves landed. Everything above this
> marker is the original review, unchanged — the historical record.
> Per-finding and per-wave status below, each with a one-line evidence
> pointer. The wave plan is `docs/interface-fix-plan.md`; the breakdown
> summary is `docs/breakdown/05-operation/interface-remediation-waves.md`
> (INFO-073).

## Findings F1–F10

| # | Finding | Status | Evidence |
|---|---------|--------|----------|
| F1 | Prompt/API vocabulary drift | **Fixed** (W0, W1) | one prompt (`src/dhc/llm/agent_system_prompt.txt`), API section generated from the registry via `prompt_section()`; conformance test `tests/llm/test_prompt_conformance.py` (5 tests) |
| F2 | No single source of truth for the namespace | **Fixed** (W1) | `src/dhc/framework/surface.py` — 47 entries (29 core / 3 advanced / 15 internal); `docs/agent-api.md` generated from it by `tools/generate_agent_api.py`, freshness test `tests/docs/test_agent_api_docs.py` |
| F3 | `messenger.read` unusable — `Message` has no id | **Fixed** (W3) | `Message.id` (`src/dhc/data/models.py:316`); `answers(question_id)` reads by id |
| F4 | Quick start is an echo bot; README claims false; dead links | **Fixed** (W2, W7) | README quick start rewritten (≤14 concepts, links resolve); `docs/quickstart.md` executed in CI by `tests/docs/test_quickstart_docs.py` |
| F5 | Flagship demo crashes off the author's machine | **Fixed** (W2) | `examples/value_demo.py` portable; `tests/test_value_demo_clean.py` runs it from a clean cwd |
| F6 | 4 ways to await, 2 to send, 3 room names, 3 settles | **Fixed** (W3, W1) | `await_`/`gather` core; `send` the core verb, `messenger` advanced facade; `room_name` canonical; one settle path (`complete`/`fail`) |
| F7 | `complete(artifacts=...)` ids-only; magic strings; silent aliases | **Fixed** (W3) | artifact coercion (objects or ids); loud errors on unknown ids/rooms; `channel_read` a deprecated alias with `DeprecationWarning` (`src/dhc/tooling/channel_tools.py:141`) |
| F8 | Silent no-ops (`!steer`, `/resume`, unknown room, archive fallback) | **Fixed** (W6) | `steer()` returns real delivery status (`src/dhc/ui/operator.py:177`); default `CheckpointStore` so `/resume` works; unknown-id and unknown-room raise loud errors |
| F9 | Config split-brain | **Fixed** (W5) | `HarnessConfig` canonical, `Settings` a read-only view (`src/dhc/data/config.py`); `ALIASES` + `DeprecationWarning` (`src/dhc/framework/caps.py:139`); `harness.json.example` generated (`tools/generate_harness_example.py`); `--config` flag |
| F10 | 13 undeclared attributes; monkey-patched privates | **Fixed** (W4) | typed `WiredRuntime` (`src/dhc/wiring.py:233`); `UnknownAgentError` (`src/dhc/errors.py:41`); public helpers `agents_snapshot`/`is_stopped`/`caps_state` (`src/dhc/framework/runtime.py:774-799`) |

## Root causes (§7)

- #1 (addition without consolidation) — addressed by the tier system
  (core/advanced/internal) and the registry as single source; the
  deletion wave for tiered-out names remains future work per §12.3.
- #2 (no drift guard) — addressed: conformance test (prompt↔registry),
  freshness test (docs↔registry), executed tutorial (docs↔code).
- #3 (config accretion) — addressed (W5).
- #4 (docs written for auditors, not users) — addressed (W7): a
  quickstart that CI executes, a generated API reference, a README
  quick start that forces ≤14 concepts.

## Accepted deviations

- `max_turn_seconds` stays a distinct per-step timeout (W5, deliberate):
  it is the step budget; `llm.call_timeout_seconds` is the LLM call
  timeout. Two different budgets, both real.
- `runtime.artifact_store_real` is deprecated, forwarding to
  `runtime.artifact_store` (the `StoreAdapter`) — removal deferred to
  the §12.3 deletion wave.
- `run_block` no longer takes a `timeout` parameter (planned W4.4,
  resolved in the W7 close-out): the param was an unenforced lie; the
  outer step timeout is the only bound. Both `ReplEngine.run_block`
  (`src/dhc/framework/repl.py:238`) and the fabrication kit's wrapper
  (`src/dhc/tooling/fabrication.py:236`) are clean — no caller passes
  a timeout.
