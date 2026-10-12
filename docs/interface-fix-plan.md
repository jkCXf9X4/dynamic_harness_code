# Interface Remediation Plan

**Date:** 2026-10-12
**Companion to:** [`interface-review.md`](interface-review.md) (findings F1–F10 refer to its severity table)
**Objective:** fix all ten review findings without weakening the invariants that make dhc worth using (at-most-once settlement, crash containment, content-addressed artifacts, deterministic mock testing).
**Status:** plan only — no implementation, no commits (per repo policy; each wave lands for manual review).

---

## 1. Success criteria (measurable)

| # | Criterion | Today | Target |
|---|-----------|-------|--------|
| S1 | Prompt↔API conformance test green (every prompt-claimed call exists with matching arity; every core surface name documented) | fails (F1) | green, in CI |
| S2 | Hand-maintained API strings in prompts | 3 drifted copies | 0 (all generated from one registry) |
| S3 | `value_demo.py` on a clean clone | crashes (F5) | completes; asserted by a clean-checkout CI job |
| S4 | Documented agent verbs for await/send/topic | 4 / 2 / 3 | 1 each |
| S5 | `messenger.read` usability | broken (F3) | end-to-end test |
| S6 | README claims | echo bot advertised as real LLM; dead links (F4) | every claim true, every link resolves |
| S7 | Concepts forced on a first-run user | ~28 | ≤ 14 |
| S8 | Test suite | 394 pass | ≥ 394 pass at every wave boundary |
| S9 | Config sources for the same knob | up to 4 names | 1 canonical + generated example file |
| S10 | Undeclared post-construction attributes on the wired runtime | 13 (F10) | 0 (typed `WiredRuntime`) |

## 2. Strategy

1. **Registry first.** The root cause of the worst findings (F1, F2) is that the agent surface exists as four hand-copied lists. Every other fix that touches docs, prompts, or `list_tools` depends on building the single source of truth first (Wave 1) — so it goes first, before any API reshaping.
2. **Ship green.** Every wave ends with the full suite passing. Golden tests that pin current bytes are *contracts*, and changing them is legitimate — but each change is a named, deliberate commit-sized unit with its own rationale, never a side effect.
3. **Generate, don't copy.** Anything that describes the API (prompt section, `list_tools`, docs reference, `harness.json.example`) is generated from the code that defines it. Hand-maintained copies are deleted.
4. **Tier, don't remove, where removal is risky.** The surface registry distinguishes `core` (goes in the prompt), `advanced` (visible via `list_tools`), and `internal` (never advertised). Deprecation happens by moving things down tiers first, deleting in a later wave once nothing references them.
5. **Fix the user-visible lies earliest.** Wave 2 (onboarding truth) is independent of Wave 1 and cheap; it runs in parallel.

## 3. Wave overview and dependency order

```
W0 drift guard ──► W1 surface registry ──► W3 agent API consolidation ──► W7 docs
                                            (docs regenerate last)
        └──────────► W2 onboarding truth (independent, parallel)

W4 embedder hygiene ──► W5 config unification ──► W6 operator UX ──► W7
```

| Wave | Fixes | Effort | Risk |
|------|-------|--------|------|
| W0 Safety net & drift guard | F1 (test side) | 0.5–1 d | low |
| W1 Surface registry (single source of truth) | F1, F2 | 3–5 d | medium (golden prompt bytes change) |
| W2 Onboarding truth | F4, F5 | 1–2 d | low |
| W3 Agent API consolidation | F3, F6, F7 | 4–6 d | medium (widest test churn) |
| W4 Embedder hygiene | F10 | 3–5 d | medium (10 test files touch privates) |
| W5 Config unification | F9 | 2–4 d | medium |
| W6 Operator UX | F8 | 1–2 d | low |
| W7 Generated docs & permanent guardrails | S7, S10 closeout | 2–3 d | low |

**Total:** ~17–28 dev-days. **Fast track (review's P0):** W0 + W1 + W2 ≈ one week and removes both Critical findings.

---

## 4. Wave 0 — Safety net & drift guard (F1, test side)

**Goal:** make prompt↔API drift a *failing test* before fixing it, so it can never silently regress again.

**Work items**

- W0.1 New `tests/llm/test_prompt_conformance.py`:
  - Parse every callable claim in `_SURFACE_DOC` and (after W1) the registry-generated prompt section; assert each name is present in a freshly-wired namespace (`build_runtime(mock=True)`) and each `inspect.signature` arity matches the claim (catches the `escalate(reason)` class of bug).
  - Assert the reverse direction: every registry entry marked `core` appears in the prompt.
  - Assert the reverse direction for the *unwired* prompts: `agent_system_prompt.txt` and any surviving prompt file contain no callable references that don't resolve in the wired namespace (catches `converse`, `report`, `delegate`, `plan`).
- W0.2 Run it. It fails today (F1 documented as a red test). Record the failure list in the plan's working notes.
- W0.3 CI: assert `examples/value_demo.py` runs green from a **clean checkout** (`git clean -xfd` clone in the job) — the machine-specificity guard for F5.

**Acceptance:** conformance test exists and is red for exactly the drift enumerated in the review; clean-checkout demo job exists (also red today).
**Test impact:** additive only; suite otherwise untouched.

---

## 5. Wave 1 — Surface registry: one source of truth (F1, F2 — Critical)

**Goal:** one registry defines the agent surface and drives the prompt, `list_tools`, and (in W7) the docs.

**Design**

- W1.1 New module `src/dhc/framework/surface.py`:

  ```python
  @dataclass(frozen=True)
  class SurfaceEntry:
      name: str            # injected name, e.g. "read_artifact"
      fn: Callable         # the binding actually injected
      doc: str             # one line, written for an LLM reader
      tier: Literal["core", "advanced", "internal"]

  class SurfaceRegistry:
      def register(self, entry: SurfaceEntry) -> None: ...
      def namespace(self) -> dict[str, Callable]: ...      # what gets injected
      def prompt_section(self) -> str: ...                  # generated _SURFACE_DOC replacement
      def list_tools(self) -> list[str]: ...                # core + advanced
  ```

- W1.2 Refactor the four registration sites to register entries instead of (or while) injecting:
  - core: `Runtime._build_namespace` (`runtime.py:462-501`) — `spawn`, `await_`, `poll`, `send`, `complete`, `fail`, `cancel`, `status`, `result`, `tool`, `bash`, `children_of`, `agent`;
  - artifact tools (`artifact_tools.py:180` registration): `publish`, `read_artifact`, `archive`, `list_artifacts` — **`read_artifact` moves to tier `core`** (this alone fixes the omission);
  - channel tools (`channel_tools.py:236`): `escalate`, `ask_operator`, `post`, `channel_read`, `room`, `messenger`;
  - framework tools (`framework_tools.py:150`): `list_tools`, `events`;
  - fabrication kit (`fabrication.py:530-552`): registered as tier `internal`/`advanced` — the 15 kit names stay injectable but stop being prompt-visible unless explicitly promoted (they were never advertised today; no behavior change).
- W1.3 Replace the private-method reassignment chain (`runtime._build_namespace = build` at `wiring.py:225`, `framework_tools.py:150`, `channel_tools.py:236`, `artifact_tools.py:180`) with an ordered, public registration:

  ```python
  runtime.register_namespace_builder(builder)   # appends, documented order
  ```

  `_build_namespace` composes all builders in registration order — same result, no monkey-patching, order is inspectable (`runtime.namespace_builders`).

- W1.4 **Prompt generation.** `default_build_prompt` (`driver.py:82-118`) takes its API section from `registry.prompt_section()`. Delete the hand-written `_SURFACE_DOC` literal (`driver.py:38-47`).
- W1.5 **Prompt consolidation (decision D1, recommendation adopted):**
  - `agent_system_prompt.txt` becomes the single doctrine prompt: strip its inline surface list (lines 26–27), rewrite its drift (`converse`, `report`, `plan`, `prune`, `escalate(reason)` → 2-arg) to match the registry, and **wire it** into `default_build_prompt` as the base text (it already accepts a `system_prompt` prepend, `driver.py:84-97`).
  - Delete `ORCHESTRATOR_SYSTEM_PROMPT` and the superseded composition code in `prompts.py` (`prompts.py:60-82, 157-163`) — verified earlier that only `prompts.py` itself and tests import them. Keep `build_system_prompt(role=...)` as the thin role-overlay helper.
  - One prompt, one vocabulary, generated API section. The doctrine prose stays hand-written but the W0 conformance test now guards it against callable-name drift.
- W1.6 `list_tools()` (`framework_tools.py:76-91`) reads from the registry — it currently lists less than what is injected.

**Decisions**

- **D1 — prompt shape:** *adopted:* thin core + registry-generated API section + the doctrine `.txt` as base. *Rejected:* keeping three prompts (status quo), or putting all ~49 names in the prompt (token cost, S1/S7 regression).
- **D2 — tier assignments:** initial `core` set = the 18 names in today's `_SURFACE_DOC` **plus** `read_artifact`, `list_artifacts`, `post`, `channel_read`, `list_tools`. Everything else `advanced`/`internal`. Tunable later by editing one file.

**Acceptance:** W0 conformance test turns green; `GOLDEN_PROMPT` in `tests/llm/test_prompt_assembly.py` updated **deliberately** (see risk R1); `grep -rn "delegate(\|converse(\|report()" src/dhc/llm/` returns nothing; no `_SURFACE_DOC` literal remains; `list_tools()` ⊇ registry core+advanced, exactly.
**Test impact:** update `test_prompt_assembly.py` (golden bytes), `tests/llm/test_prompts.py` (key-phrase assertions against the rewritten `.txt`), `tests/tooling/test_framework_tools.py` (list_tools contents). All other suites must pass unmodified — the injected namespace is unchanged; only its description changed.

---

## 6. Wave 2 — Onboarding truth (F4, F5)

**Goal:** every public claim about getting started is true; the flagship demo runs anywhere.

**Work items**

- W2.1 `examples/value_demo.py`:
  - derive `REPORT_PATH` from the runtime's `artifact_root` (passed to `build_runtime` at line 131) — delete the hardcoded `/home/eriro/...` string (`value_demo.py:51-54`);
  - extract the mock scripts (`CHILD_REPORT/CHILD_OK/CHILD_FAIL/ROOT_SCRIPT`) into a shared helper imported by both the demo and `tests/test_integration.py` (they are near-verbatim duplicates today) — e.g. `examples/_mock_scripts.py` or `tests/helpers.py`;
  - replace the `rt.artifact_store_real` read (`value_demo.py:160-165`) with the public access added in W4.1 (sequence note: if W2 lands before W4, keep the read but add a comment pointing at W4; do not block W2 on W4).
- W2.2 Root `README.md`: fix all `breakdown/...` links → `docs/breakdown/...` (11-12, 52-66); correct the quick start (45-48): `dhc` chat is echo-only regardless of `OPENAI_API_KEY`; document `python3 -m dhc.ui.terminal` as the real-LLM entry point.
- W2.3 Echo honesty (decision D3, adopted): when `ChatSession` runs with the `DefaultDriver` fallback, print a one-line banner: *"echo mode: no LLM driver wired — set OPENAI_API_KEY and use `python3 -m dhc.ui.terminal` for the real driver"*. Also fix `terminal.py:19,518` docstring module path. *Rejected for now:* wiring `LLMDriver` into `dhc` chat — the two-entry-point split is a documented design decision (INFO-070); revisit only if users ask.
- W2.4 `harness.json.example`: add the 3 missing `safety` keys (`max_workspace_bytes`, `max_children`, `max_messages_per_step`) — superseded in W5 by generation from the model, but the file must not lie in the meantime.

**Acceptance:** W0.3 clean-checkout job green; `grep -rn "breakdown/" README.md` shows only `docs/breakdown/`; chat banner printed in `tests/ui/` (or operator) test; demo runs on a machine without `/home/eriro`.
**Test impact:** `tests/test_integration.py` updated for the shared mock-script helper (no semantic change); one new banner test.

---

## 7. Wave 3 — Agent API consolidation (F3, F6, F7)

**Goal:** one documented idiom per concept; every advertised call works; no silent failures. Ordered additive-first so the suite stays green at each step.

**Warming: artifact ergonomics (F7)**

- W3.1 `complete(headline, artifacts=())` and `Result.artifacts` accept `Artifact` objects **or** ids: coerce via a single `_artifact_ids(items)` helper (artifact object → `.id`, str → as-is, else `TypeError` naming the accepted types). Update `models.py:140-149` docstring. This kills the publish→id→complete juggling for the common case.
- W3.2 `read_artifact` level aliases: make `"full"` and `"raw"` **official** (they work today, `artifact_tools.py:88`) and fix the error message to list all five (`artifact_tools.py:94`). *Chosen over rejecting:* agents will pass these regardless; documenting reality beats a new failure mode.

**Messaging (F3, F6)**

- W3.3 Add `Message.id: str` (uuid or content hash, default factory) to `models.py:270-278` (frozen model — additive field with default is compatible). `messenger.read(message_id)` now works from `messenger.inbox()` output. End-to-end test: send → inbox → read → assert body.
- W3.4 Unify the room-topic parameter name to `room_name` across `room(name)`, `post(room_name, body)`, `channel_read(topic → room_name)` (`channel_tools.py:187-193`); keep `topic=` as a deprecated keyword alias for one wave.
- W3.5 Demote `messenger.send` to `advanced` tier (it is documented sugar over `send`); the prompt teaches `send` only. No code removal this wave.
- W3.6 Close the escalation loop: register `ack(escalation_id)` and `answers(question_id)` (thin wrappers over the existing-but-unregistered `EscalationChannel.ack` and `OperatorQuestionChannel.answers_for/answer`, `channels.py:255,321,351`) as `core` surface entries. `ask_operator(question)` returns the question id so the asker can poll `answers(qid)` instead of excavating `events()`.
- W3.7 `room(name)` side-effect join: keep the join (tests depend on it) but add `room_messages(room_name)` as an explicit non-joining read; the prompt teaches `room_messages` for polling, `room` for joining. `channel_read` becomes the deprecated alias (moved to `advanced`).

**Await/poll idiom (F6, decision D4 — adopted: tier, don't break)**

- W3.8 Teach exactly two idioms in the registry `core` tier: the functions `await_(h)` / `poll(h)` and the yield forms `Await(h)` / `Poll(h)` / `Sleep(s)` for cooperative contexts. `AgentHandle.await_()`/`.poll()`/`.cancel()` remain (host-side conveniences, tier `advanced`) but leave the prompt. Add a fan-out helper:

  ```python
  def gather(handles, *, return_failures=False) -> list[Completion]
  ```

  implemented over the existing dispatcher (spawn-all → await-all, one `ChannelError`-free aggregation). Selective failure handling becomes `for c in gather(hs, return_failures=True): if c.status != AgentStatus.completed: ...`.

**Silent failures made loud (F7/F8 spillover)**

- W3.9 `spawn(..., **kwargs)` (`agent.py:207-208`): validate — unknown kwargs raise `TypeError: spawn() got unexpected keyword 'namespce' (did you mean 'namespace'?)`. `driver` and `namespace` remain the only pass-throughs, documented.
- W3.10 `channel_read`/`room_messages` on unknown room: raise `ChannelError` (was `[]`, `channels.py:188`). `archive()` fallback (`artifact_tools.py:109-112`): raise `ArtifactNotFoundError` when no path derivable (was: silently return the id). Each gets a test asserting the error names the offending input.

**Acceptance:** W0 conformance still green; new tests: artifact-object coercion, Message-id round-trip, gather success/failure paths, each loud-error case; every prompt-visible verb has at least one end-to-end usage test in `tests/tooling/`.
**Test impact:** tests asserting the old silent behaviors are updated with the failure-path assertions (enumerate: `channel_read` empty-list, `archive` fallback — expect ≤ 5 sites). No mock-script changes needed.

---

## 8. Wave 4 — Embedder hygiene (F10)

**Goal:** the wired runtime is a typed, inspectable object; composition is public API.

- W4.1 New `class WiredRuntime(Runtime)` in `wiring.py` with all 13 decorations **declared as class attributes with types** (`messenger`, `rooms`, `escalations`, `questions`, `dispatcher`, `boundary_log`, `bus`, `artifact_store`, `artifact_store_real`, `operator`, `mock`, `rot_detector`, `repl_engine`, plus `checkpoint_store` from W6). `build_runtime` returns `WiredRuntime`. Keep `artifact_store` (typed) and **deprecate `artifact_store_real`** with a `DeprecationWarning` property forwarding to it; migrate the demo (W2.1) and tests in the same change. Delete `artifact_store_real` in a later release once grep is clean.
- W4.2 The `register_namespace_builder` chain from W1.3 is the only composition path; delete the `# type: ignore[method-assign]` sites. Export `register_namespace_builder` in `dhc/__init__.py`.
- W4.3 `errors.py`: add `UnknownAgentError(DhcError)`; replace the six bare-`KeyError` sites (`runtime.py:626-685`) — message includes the id and the known-id count. Tests for the new error type; update tests asserting `KeyError`.
- W4.4 Truth-in-signatures:
  - `ReplEngine.run_block(..., timeout=None)`: remove the unenforced parameter (`repl.py:238-247`) after grep confirms no caller passes it;
  - `Runtime.spawn`: rename `_agent_callback` → `agent_callback: bool = False` (public, documented; internal callers updated);
  - `Runtime.spawn` auto-start (`runtime.py:280-282`): keep (convenient for tests) but make `start()` docstring state it is idempotent and that `spawn` auto-starts;
  - `Agent.cancel()` (`agent.py:264-268`): rename to `record_result()` — a method named `cancel` that does not cancel is a trap; `AgentHandle.cancel()` is the real one and stays;
  - `status()` vs `poll()`: keep both, `status` documented as the host-facing alias (removal churn not worth it).
- W4.5 Public test helpers so the 10 test files that reach into `rt._agents` / `rt._stop_flags` / `rt._caps_watchdog` / `rt._build_namespace` (found via grep: `test_context.py`, `test_direct_messaging.py`, `test_event_fanout.py`, `test_g05_parked_time.py`, `test_h04_monotonic_timebase.py`, `test_composition_wave1.py`, `test_channel_tools.py`, `test_fabrication.py`, `test_events_tool.py`, `test_framework_tools.py`) can stop doing so: expose read-only `runtime.agents_snapshot()`, `runtime.is_stopped()`, `runtime.caps_state()`. Migrate tests opportunistically; privates stay available (no forced churn) but new tests must use the helpers.

**Acceptance:** `mypy`/`pyright` (if configured) sees the decorations; `grep -rn "artifact_store_real" src/ examples/` empty except the deprecation shim; all six unknown-agent paths raise `UnknownAgentError`; suite green.
**Test impact:** `KeyError` assertions → `UnknownAgentError`; `_build_namespace` reach-ins → `register_namespace_builder`; behavior otherwise identical.

---

## 9. Wave 5 — Config unification (F9)

**Goal:** one canonical config model; aliases resolved in one place; example file generated.

- W5.1 `HarnessConfig` is canonical. `Settings` becomes a typed compatibility **view** over it (constructed from `HarnessConfig`), not a parallel source. Delete the ad-hoc merges: `read_cap` (`caps.py:31-45`) resolves via one `ConfigResolver`; `Settings.provider` (`config.py:241-262`) delegates.
- W5.2 Alias table: the 11 `_BUDGET_CAP_KEYS` aliases (`caps.py:74-86`) collapse to one explicit `ALIASES: dict[str, CapName]` with a `DeprecationWarning` on alias use. Time ceilings: `timeout_seconds` is the config name; `wall_clock` is the cap name; `max_turn_seconds` and `_DEFAULT_TIMEOUT_SECONDS` die (grep first). `max_agents` vs `max_children`: keep both as aliases of the `children` cap via the table — one definition, two accepted spellings, one warning.
- W5.3 Generate `harness.json.example` from `HarnessConfig.model_fields` (script in `tools/` or a test-time generator); a test asserts every field appears (this is what W2.4 patched by hand — now structural).
- W5.4 `--config` flag on the `dhc` chat CLI for parity with the terminal entry point.

**Acceptance:** no config key is read from more than one place (grep: `os.environ`/`getenv` calls centralized in `config.py`); example file test green; suite green.
**Test impact:** alias-deprecation warnings tests; `Settings` construction tests move to view semantics.

---

## 10. Wave 6 — Operator UX (F8)

- W6.1 `/resume` works out of the box: `build_runtime` attaches a default `CheckpointStore` under the workspace root (`checkpoint.py:91` — `CheckpointStore(root)` is self-contained), exposed as `WiredRuntime.checkpoint_store`. `operator-runbook.md:62-63` note becomes obsolete — delete it.
- W6.2 `!steer` honesty: when `Operator.steer` records to `undelivered_steers` (`operator.py:177-200`), print `"steer NOT delivered to <id> (no messenger wired)"` instead of the current success-looking `"steered <id>"` (`operator.py:346`). Test both paths.
- W6.3 Command vocabulary: chat banner lists `!quit`, `!steer`, `!inspect` with one-line help; terminal accepts `/q` as `/quit`; `!inspect`/`--inspect` on unknown ids prints `"unknown agent id: <id> (N agents known)"` instead of `status: None`.
- W6.4 `--timeout`-style removal note discipline: every shipped flag is either functional or removed from `--help` (there is precedent at `cli.py:96-99`).

**Acceptance:** new tests: `/resume` round-trip on a default runtime; steer-undelivered message; inspect-unknown message. Both banners tested.

---

## 11. Wave 7 — Generated docs & permanent guardrails (S7, S10 closeout)

- W7.1 `docs/quickstart.md`: a real tutorial built on the `tests/test_integration.py` fixture pattern (build_runtime(mock=True) → spawn → fan-out → await → read artifacts → inspect events), verified by a docs test that executes its code blocks (doctest or literal include from a tested example file).
- W7.2 `docs/agent-api.md`: generated from the registry — name, signature, one-line doc, tier, minimal example per `core` entry. Generator lives next to the registry; a test asserts the file is current (registry hash in a footer comment).
- W7.3 Concept-count audit: rewrite the README quick start to require only: install → run demo → understand `requirement`, `spawn/await`, `complete/fail`, artifacts (publish/read). Everything else links out. Target S7 (≤ 14 forced concepts).
- W7.4 Update `docs/breakdown/` records: new INFO entry pointing at the review + this plan; amend the INFO-050/070 pages that describe the superseded prompt composition and the two-entry-point echo behavior.

**Acceptance:** quickstart code blocks execute in CI; agent-api.md freshness test green; README links all resolve (add a link-checker job or test).

---

## 12. Migration & deprecation policy

1. **Additive first:** every acceptance change (Artifact-or-id, `Message.id`, `room_name` alias, `gather`) lands as *widening*; old call shapes keep working.
2. **Tier before delete:** anything removed from the prompt moves to `advanced` (still injectable, still listed by `list_tools`) for one wave before any code deletion.
3. **One deprecation release:** `artifact_store_real`, `channel_read` alias, `messenger.send`, alias config keys — `DeprecationWarning` now, deletion gated on `grep` returning only the shim, in a wave explicitly labeled "deletion".
4. **Golden tests are contracts, not fossils:** `GOLDEN_PROMPT` updates happen exactly once (W1) with the rationale in the commit message; thereafter the W0 conformance test — which checks *structure*, not bytes — is the drift guard. Byte-pinning remains for anything not covered by conformance.
5. **No forced test churn:** privates stay functional after W4.5's helpers ship; migration of the 10 test files is opportunistic.

## 13. Risk register

| ID | Risk | Likelihood | Mitigation |
|----|------|-----------|------------|
| R1 | Golden-prompt byte change (W1) alters real-LLM behavior in unmeasured ways | certain to change; impact unknown | Mock suite is unaffected (MockDriver scripts don't consume prompts). Run the real-LLM best-effort path (`value_demo.py` real mode) before/after W1 and compare completions; the conformance test prevents *structural* regressions |
| R2 | Prompt grows (core tier + doctrine .txt) → more tokens/turn | medium | Tier system caps the prompt at `core`; `advanced` reachable via `list_tools`; measure prompt bytes before/after W1 |
| R3 | W3/W4 churn breaks the 10 private-reaching test files | medium | W4.5 helpers first, opportunistic migration, privates remain functional |
| R4 | `Message.id` on a frozen model breaks event-log/persistence consumers | low | Additive default-factory field; grep event-log schema consumers; `events.jsonl` writes include ids as new keys only |
| R5 | Removing silent-failure behaviors breaks tests that assert them | medium | Enumerated in W3.10 (≤ 5 sites expected); failure-path tests replace them in the same change |
| R6 | Config unification breaks `DHC_*` env users | low | Env vars resolve through the same `ConfigResolver` (they remain supported, single read site); deprecation warnings only for *alias keys* |
| R7 | Work stacking: W2.1 demo fix touches the same lines W4.1 migrates | low | W2 may keep `artifact_store_real` with a pointer comment (noted in W2.1); rebase order W2 → W4 documented |
| R8 | Scope creep into rewriting the fabrication kit / pump internals | medium | **Out of scope by design:** the pump, fabrication kit internals, settle machinery, and event cursors are *internal* interfaces; this plan only types and documents their boundaries (W4). No behavior changes inside `pump.py`/`fabrication.py` beyond the registration refactor |

## 14. Traceability matrix

| Finding (review §1) | Wave(s) | Success criterion |
|---------------------|---------|-------------------|
| F1 prompt/API drift (Critical) | W0, W1 | S1, S2 |
| F2 no single source of truth (Critical) | W1 | S2 |
| F3 `messenger.read` unusable | W3.3 | S5 |
| F4 quick-start lies, dead links | W2 | S6 |
| F5 demo crashes on clean clone | W2, (W0.3 guard) | S3 |
| F6 duplicated verbs (await/send/topic/settle) | W3.4–3.8, W1.2 | S4 |
| F7 artifact footguns, silent failures | W3.1–3.2, W3.9–3.10 | S5 |
| F8 silent no-ops in operator UX | W6 | S6 |
| F9 config split-brain | W5 | S9 |
| F10 undeclared wiring, monkey-patched privates | W4 | S10 |

## 15. Definition of done (per wave)

1. All work items checked; suite ≥ 394 passing, 0 failed, 0 skipped (baseline).
2. The wave's acceptance criteria demonstrably met (test names listed in the wave).
3. Deprecations emitted where the policy requires; no hand-maintained API copy added anywhere (`grep` gates in W1, W5.3, W7.2).
4. `docs/breakdown/` amended if the wave invalidates a recorded claim (W7.4 collects these; waves may append).
5. Changes left uncommitted for manual review, per repo policy.

## 16. Recommended landing order

```
Week 1:  W0 → W1 (conformance green, registry, one prompt) → W2 (truth pass)
         → both Critical findings closed; S1–S6 measurable
Week 2:  W3 (agent API consolidation, additive order)
Week 3:  W4 (embedder hygiene) → W6 (operator UX; small, unblocks users)
Week 4:  W5 (config) → W7 (generated docs) → deletion wave for tiered-out
         names (§12.3)
```

Fast track if time-boxed to one week: W0 + W1 + W2 — that closes both Critical findings and all four High onboarding findings, and leaves the API consolidation (W3) as a clean follow-up.
