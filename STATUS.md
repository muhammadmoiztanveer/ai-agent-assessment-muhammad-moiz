# Build Status Tracker

> Single source of truth for **what is done** and **what is left**. Updated at the end of every phase.
> Companion docs: [`PLAN.md`](./PLAN.md) (engineering plan) · [`WHAT_TO_BUILD.md`](./WHAT_TO_BUILD.md) (plain-English scope).

**Last updated:** 2026-09-06
**Current phase:** ✅ All phases complete (0–13), including both spec bonuses + observability visualization
**Overall progress:** Phases 0–13 complete (foundation + persistence + observability + resilience + DataForSEO tools + LLM layer + 5 atomic agents + LangGraph DAG + FastAPI services & endpoints + full spec-mandated test suite + graded README + beyond-spec responsive dashboard + async/background execution bonus + API-exposed per-run observability with a DAG/metrics dashboard and live failure simulation ✅). **Both PDF-named bonuses are delivered**: circuit breaker (§3.5) and async/background run processing (§4.2).

Legend: ✅ done · 🔄 in progress · ☐ not started

---

## Phase checklist

### ✅ Phase 0 — Scaffolding & tooling

- [x] Verify latest stable library versions (backend + frontend)
- [x] Backend package layout (`app/api`, `schemas`, `services`, `graph`, `agents`, `tools`, `integrations/dataforseo`, `llm`, `resilience`, `observability`, `db`)
- [x] `pyproject.toml` with pinned deps + ruff/black/mypy/pytest config
- [x] `requirements.txt` mirror
- [x] `app/config.py` — Pydantic Settings reading all env keys (+ validators)
- [x] FastAPI app factory + `python -m app` entrypoint + `/health`
- [x] `.env.example` documenting all configuration
- [x] `Makefile` (install / run / test / lint / format / typecheck / check / clean + frontend targets)
- [x] Frontend foundation (React 19 + Vite 8 + TS 7 + Tailwind 4) — beyond-spec
- [x] Verified: venv install, ruff, mypy, pytest, app boot, frontend build all green
- [x] `git init` + first commit `chore: project scaffold + config + tooling`

### ✅ Phase 1 — Persistence

- [x] `db/database.py` (engine/session factory, `init_engine`/`init_db`, `session_scope`, `get_db` dep, SQLite dir auto-create + `check_same_thread`)
- [x] `db/models.py` — Profile, Run, Query, Recommendation (4 tables); StrEnum enums stored as portable VARCHAR; JSON columns; tz-aware UTC timestamps; cascade relationships
- [x] `db/repositories.py` — typed data-access (profiles, runs, queries w/ filter+sort+paginate, recommendations, recheck update/replace, `profile_summary` stats)
- [x] `db/__init__.py` re-exports engine helpers + models + enums
- [x] Round-trip tests: `tests/test_persistence.py` (durability round-trip, filters+pagination, summary stats, recheck update/replacement)
- [x] Verified: ruff + black + mypy (21 files) clean, pytest 6 passed; `init_db()` creates all 4 tables with exact PLAN §3.2 columns
- [x] Commit: `feat(db): models + repositories for profiles/runs/queries/recommendations`

### ✅ Phase 2 — Observability core

- [x] `observability/logging.py` (structlog JSON to stdout + secret redaction via word-segment matching; `log_node_event` helper; wired into app startup)
- [x] `observability/tracing.py` (correlation-id `contextvar` bound into structlog; `correlation_context`, `timed_span`)
- [x] `observability/metrics.py` (per-run `RunMetrics`: node latency, success/fail, API-call + retry totals, tokens; `summary`/`log_summary`)
- [x] `observability/__init__.py` re-exports
- [x] Tests: `tests/test_observability.py` (redaction incl. over-redaction guard, correlation-id propagation, metrics aggregation, structured summary)
- [x] Verified: black + ruff + mypy (24 files) clean, pytest 16 passed; live demo shows correlation_id on every line, secrets redacted, `total_tokens` preserved
- [x] Commit: `feat(obs): structured logging, correlation-id tracing, metrics collector`

### ✅ Phase 3 — Resilience core

- [x] `resilience/errors.py` — `ClassifiedError` (code, retryable, status_code, `retry_after_s`, redaction-safe detail, `as_dict`); `ResilienceError`/`RetryableError`/`NonRetryableError`; `classify()` mapping httpx transport errors + `Response`/`HTTPStatusError` + `ValueError` + unknown; `Retry-After` parsing (delta-seconds **and** HTTP-date, clamped ≥ 0); `is_retryable`, `to_resilience_error`
- [x] `resilience/retry.py` — `RetryPolicy` (+ `from_settings`); `compute_delay` (exponential `base·2^(n-1)`, capped, **full jitter** `uniform(0, delay)`, `Retry-After` override still capped); `retry_call` (fast-fail on non-retryable, retries transient, exhausts → `RetryableError`, injectable `sleep`/`rng`, `on_retry` callback for metrics)
- [x] `resilience/circuit_breaker.py` — `CircuitState` (closed/open/half-open); `CircuitOpenError` (non-retryable); thread-safe `CircuitBreaker` (injectable clock, `allow`/`record_success`/`record_failure`/`call`, half-open trial, `record_failure_on` predicate, `from_settings`)
- [x] `resilience/__init__.py` re-exports
- [x] Unit tests: `tests/test_resilience.py` (40 tests) — classification of all status classes + transport errors, `Retry-After` (int + date), backoff growth/cap/jitter-bounds/override, retry counting, fast-fail, exhaustion, breaker open→cooldown→half-open→close/reopen, `call` wrapper + failure predicate
- [x] Verified: ruff + black clean, mypy clean (27 files), **pytest 56 passed**; live demo confirmed backoff `[0.5, 1.0]`, non-retryable fast-fail, breaker trips → `open`, 429 (retryable + `Retry-After=5.0`) vs 401 (non-retryable)
- [x] Commit: `feat(resilience): retry/backoff/jitter, classification, breaker`

### ✅ Phase 4 — DataForSEO integration + tools

- [x] `integrations/dataforseo/endpoints.py` — `Endpoint` registry (4 logical calls: serp_organic, ai_overview, llm_visibility, keyword_metrics) so "one tool = one API call" is structural
- [x] `integrations/dataforseo/mock/fixtures.py` — deterministic (sha256-seeded) fixtures mirroring the real `tasks[].result[]` envelope; reproducible timestamps (no wall-clock `now()`)
- [x] `integrations/dataforseo/client.py` — httpx client with explicit connect+read timeouts (R13), mode switch (`mock`|`live`|`stub`), Basic auth for live, retry+breaker pipeline, `mock_hook` fault-injection seam, `last_retry_count`
- [x] `tools/schemas.py` — 4 strict Pydantic arg schemas (typed, described, bounded, `extra="forbid"`)
- [x] `tools/base.py` — `ToolResult` + `ValidatedTool` (validate-before-call; malformed args → clean non-retryable result, never crashes; `json_schema()` for LLM binding)
- [x] `tools/dataforseo_tools.py` — `build_dataforseo_tools()` registry, one `ValidatedTool` per logical call
- [x] Tests: `tests/test_tools.py` (23 tests) — happy-path shapes, determinism, arg validation (blank/missing/unknown/out-of-range/empty), retry-then-succeed, exhaustion → retryable failure, breaker fast-fail, live mode via `MockTransport` (200/401/503), stub mode
- [x] Verified: ruff + black (39 files) clean, mypy clean (33 files), **pytest 79 passed** (+23)
- [x] Commit: `feat(tools): typed DataForSEO tools + validating wrapper + mock client`

### ✅ Phase 5 — LLM layer

- [x] `llm/base.py` — provider-neutral types (`Message`, `ToolSpec`, `ToolCall`, `TokenUsage`, `LLMResponse`, `LLMRequest`) + `LLMClient` ABC with built-in token accounting (`total_tokens`, usage callback) + `specs_from_tools`
- [x] `llm/client.py` — `OpenAILLMClient` (LangChain `ChatOpenAI` adapter: binds tools so the model chooses tool + args, normalizes `usage_metadata`→`TokenUsage`, wraps calls in `retry_call` with LLM-aware retryable/non-retryable classification) + `build_llm` factory
- [x] `llm/mock.py` — `ScriptedLLMClient` (ordered canned responses **or** responder callable; deterministic for tests and the keyless runtime path)
- [x] `llm/prompts.py` — 5 versioned atomic-agent system prompts (each states its one job + what it must NOT do); `PROMPT_VERSION`, `get_prompt`
- [x] `llm/__init__.py` re-exports
- [x] Config: `LLM_MODE` (`auto`|`openai`|`mock`), `LLM_MAX_RETRIES`, `use_real_llm` property, `openai`-mode key validator; `.env.example` documents both
- [x] Tests: `tests/test_llm.py` (23 tests) — value types, tool binding + OpenAI function render, prompts, scripted client + token accounting, OpenAI client via injected fake chat model (content/tool-call/usage extraction, retry-then-succeed, non-retryable fast-fail, 5xx exhaustion), factory selection
- [x] Verified: ruff + black clean (44 files), mypy clean (37 files), **pytest 102 passed** (+23); live demo confirmed keyless→mock client, OpenAI tool render, cumulative tokens 115 (=40+75), usage callback firing
- [x] Commit: `feat(llm): provider client, tool binding, token accounting`

### ✅ Phase 6 — Agents (the 5, atomic)

- [x] `agents/types.py` — framework-neutral typed contracts (`ProfileContext`, `PlannedCall`, `RetrievalPlan`, `RetrievalOutcome`, `NormalizedQuery`, `Insight`, `RecommendationDraft`, `AnalysisResult`, `Report`); reuse persistence enums (`VisibilityStatus`/`ContentType`/`Priority`) so agent output maps to DB rows with zero drift; each carries `as_dict()` for state/JSON
- [x] `agents/planner.py` — `PlannerAgent`: LLM chooses tools+args (R7) with a deterministic, profile-grounded fallback plan; filters unknown tools; bounds call count. Plans only — never fetches
- [x] `agents/retrieval.py` — `RetrievalAgent`: executes planned calls via `ValidatedTool` (validate-before-call), collects raw `ToolResult`s + classified errors; never normalizes/summarizes; never crashes
- [x] `agents/extraction.py` — `ExtractionAgent`: deterministic parse of the `tasks[].result[].items[]` envelope across all 4 endpoints into `NormalizedQuery`; brand-domain visibility + position detection; status derivation (visible/not_visible/unknown). No scoring, no prose
- [x] `agents/analysis.py` — `AnalysisAgent` + `opportunity_score()`: deterministic score in [0,1] (formula per PLAN §5.4/README), rank, draft recommendations (content-type + priority heuristics), optional LLM narrative with deterministic fallback. Never calls tools / re-fetches / formats final doc
- [x] `agents/report.py` — `ReportAgent`: assembles structured `report_json` + human `report_summary` (LLM prose with deterministic fallback, partial/degraded note). Summarizes only — no tools, no re-scoring
- [x] `agents/__init__.py` re-exports
- [x] Per-agent isolation unit tests: `tests/test_agents.py` (17 tests) — planner LLM-path + deterministic fallback + unknown-tool filtering + call bounding; retrieval success/invalid-args/unknown-tool classification; extraction normalization + visibility + unknown-status + failed-result skipping; opportunity_score formula correctness + [0,1] bounds + ranking; recommendation heuristics; LLM vs deterministic narrative/summary; report shape + degraded note + empty case
- [x] Verified: black + ruff clean (51 files), mypy clean (43 files), **pytest 119 passed** (+17); live demo chained all 5 agents keyless (mock) → Planner 7 calls → Retrieval 7 ok → Extraction 4 queries → Analysis 4 insights/4 recs → Report summary, structured JSON logs per agent
- [x] Commit: `feat(agents): 5 atomic single-responsibility agents`

### ✅ Phase 7 — Graph assembly

- [x] `graph/state.py` — typed `PipelineState` (TypedDict, `total=False`) + node-name constants + `initial_state`; each node writes only its own slice so the agents' atomicity survives inside the graph
- [x] `graph/dependencies.py` — `PipelineDependencies` + `build_dependencies` (per-run wiring: DataForSEO client → validated tools → LLM → the 5 agents; LLM token-usage callback feeds the run's `RunMetrics`)
- [x] `graph/nodes.py` — instrumented node wrappers (per-node `timed_span`, `RunMetrics.record_node`, structured `graph.node.finish` logs; a raising node is classified and degrades to fallback instead of crashing the graph)
- [x] `graph/edges.py` — conditional routers `route_after_plan` / `route_after_retrieve` / `route_after_normalize`, each guarding the deterministic fallback branch
- [x] `graph/build.py` — `build_graph` compiles the `StateGraph` with named nodes + conditional edges (START→plan→retrieve→normalize→analyze→report, plus fallback→report); `run_pipeline` binds a correlation id + metrics collector and returns the final state; `build_default_graph` convenience
- [x] `graph/__init__.py` re-exports the public surface
- [x] Integration tests: `tests/test_graph.py` (8 tests) — happy path → `completed` with all response fields + one metric per executed node; total retrieval failure → `failed` with a report (no crash, circuit breaker trips); partial retrieval failure → `partial`; the three conditional routers; compiled-graph named nodes
- [x] Verified: black + ruff clean (57 files), mypy clean (48 files), **pytest 127 passed** (+8); keyless demo confirmed happy path + simulated-outage fallback with correlation-id on every log line and a per-run metrics summary
- [x] Commit: `feat(graph): LangGraph DAG with conditional routing + fallback`

### ✅ Phase 8 — Services + API

- [x] `schemas/{profile,query,recommendation,run}.py` — Pydantic request/response contracts (field-for-field per spec §4; `extra="forbid"` on inputs); `schemas/__init__.py` re-exports
- [x] `api/errors.py` — `APIError`/`NotFoundError` + `install_error_handlers` (uniform `{"error": {code, message, details}}` envelope; maps domain errors → status, `RequestValidationError` → 422, unhandled → 500 without leaking traces)
- [x] `services/profile_service.py` — `create_profile`, `get_profile_detail` (+ summary stats), `list_profile_queries` (filter/sort/paginate over the latest run), `list_profile_recommendations`; each owns a short `session_scope` and returns ready-to-serialize models
- [x] `services/pipeline_service.py` — `run_profile_pipeline`: loads the profile (short txn) → runs the DAG **outside** any transaction (no connection held for the 10–30s run) → persists run + queries (from ranked insights) + recommendations (linked to their target query) in a final txn → returns the full `RunResponse`
- [x] `services/recheck_service.py` — `recheck_query`: builds a single-keyword plan across all four tools, re-runs Retrieval → Extraction → Analysis, then updates the query's metrics and regenerates its recommendations
- [x] `api/routes/{profiles,runs,queries,recommendations}.py` + `routes/__init__.py` (`all_routers`); the 6 endpoints under `/api/v1`
- [x] `api/app.py` — lifespan initializes the DB (`init_db`), error handlers installed, routers included, `/health` + CORS retained
- [x] API contract tests: `tests/test_api.py` (14 tests) — 201/200/404/422 codes, response shapes, opportunity-score sort, `min_score`/`status`/pagination filters, uniform error envelope, recheck update path, empty-run edge case
- [x] Verified: black + ruff clean (70 files), mypy clean (60 files), **pytest 141 passed** (+14); live `python -m app` boot on a temp DB → `/health` 200, `/docs` 200, all 6 OpenAPI paths, live `POST /run` → `completed`; end-to-end TestClient flow (create → run → queries/recs/recheck) green
- [x] Commit: `feat(api): FastAPI endpoints + services wiring`

### ✅ Phase 9 — Full test suite

- [x] `tests/conftest.py` — shared hermetic fixtures (`FAST_RETRY`, `make_settings`, `make_profile`, `make_deps`, `run_full_pipeline`; `api_client` temp-SQLite TestClient + `create_profile` factory) so the spec-named files stay focused
- [x] `test_happy_path.py` (8 tests) — full DAG run at the graph level **and** through the HTTP API → `completed`, every mandated response field present, insights == extracted_count, one metric per node in order, top insights sorted by opportunity score
- [x] `test_failure_retry.py` (16 tests) — retryable vs non-retryable classification (timeouts/429/5xx vs 400/401/404/422), `Retry-After` parsing, exponential backoff growth/cap/full-jitter-bounds/override, retry executor (retry-then-succeed, fast-fail, exhaustion), and an integration retry-then-succeed on a real tool call
- [x] `test_fallback_degradation.py` (4 tests) — total retrieval failure → `failed` + `error_flag` + report (no crash), circuit breaker trips, analysis skipped; partial failure → `partial` with analysis still running
- [x] `test_tool_validation.py` (10 tests) — JSON schema exposed; blank/missing/unknown/out-of-range/empty args rejected as clean non-retryable `ToolResult` **before** any API call; redaction-safe error detail; bad-args plan degrades gracefully through the Retrieval agent (never crashes the graph)
- [x] `test_api_contracts.py` (13 tests) — 201/200/404/422 codes, exact response shapes, opportunity-score sort, `min_score`/`status`/pagination filters, uniform error envelope, recheck update path, empty-run edge case
- [x] `test_opportunity_score.py` (10 tests) — exact formula values, hard `[0,1]` bounds under extreme/degenerate inputs, monotonicity in volume/difficulty/visibility-gap, configurable-weight sensitivity, 4-dp rounding, Analysis-agent ranking
- [x] Verified: black clean (77 files), ruff clean, mypy clean (60 app files), **pytest 202 passed** (+61); all hermetic (mock DataForSEO + scripted LLM + temp SQLite), ~1.1s, no network
- [x] Commit: `test: happy path, failure+retry, fallback, tool validation, API contracts`

### ✅ Phase 10 — README + polish (graded deliverable)

- [x] Full README: architecture + ASCII/Mermaid DAG diagram, setup, the 5 agents, `opportunity_score` formula, API overview + curl walkthrough
- [x] Worked **simulated-failure** example (how to trigger via `mock_hook`, expected fallback/partial output) + real success **and** degraded JSON log/trace excerpts (correlation-id bound) + production observability roadmap
- [x] Known limitations & future-improvements section
- [x] All traceability rows flipped to ✅; final lint/type/test pass (ruff + mypy + black + 202 tests green)
- [x] Commit: `docs: README with architecture, DAG diagram, failure & observability examples`

### ✅ Phase 11 — Responsive dashboard frontend (beyond-spec)

- [x] `lib/types.ts` (contracts mirroring the API), `lib/api.ts` (typed client + `ApiError` envelope parsing), `lib/format.ts` (presentation helpers)
- [x] Profile form (`ProfileForm.tsx`) — name/domain/industry/description/competitors, inline validation + error banner
- [x] Run pipeline + live status (`RunPanel.tsx`) — trigger `POST /run`, spinner during run, status badge, degraded banner
- [x] Run summary — planned calls, extracted records, total tokens, insight count, run + correlation IDs
- [x] Queries table (`QueriesTable.tsx`) — sorted by score, `min_score` + visibility-status filters, pagination, per-row **recheck**
- [x] Insights (top, scored) & recommendations (`Recommendations.tsx`) — content-type, priority, rationale, keyword chips
- [x] Report view (`ReportView.tsx`) — human summary + run-trace panel (correlation id) + collapsible raw JSON
- [x] Empty/loading/error states in every panel; mobile-first, keyboard navigable, dark-mode aware; live `/health` connection badge
- [x] Verified: `npm run build` clean (tsc strict + vite, 25 modules); dev server serves and reaches the API (health polling confirmed in backend logs)
- [x] Commit: `feat(frontend): responsive React dashboard (beyond-spec extra)`

### ✅ Phase 12 — Async / background run execution (spec §4.2 bonus)

> The spec allows synchronous runs and lists async/background processing as an explicit **bonus**. This
> phase adds real background execution with a `queued → running → terminal` lifecycle and a poll endpoint,
> **without** any external broker — so the single-command, zero-credential run is preserved. A
> Celery/RQ-backed implementation drops into the same `RunQueue` interface for horizontal scale (README).

- [x] `db/models.py` — `RunStatus.QUEUED` + `is_terminal` property (queued/running are transient; completed/partial/failed are terminal)
- [x] `config.py` + `.env.example` — `RUN_WORKER_CONCURRENCY` (worker-pool size, default 4)
- [x] `services/run_queue.py` — `RunQueue` ABC + `ThreadPoolRunQueue` (in-process `ThreadPoolExecutor`, worker-exception guard) + process-wide `init/get/shutdown/set` accessors
- [x] `services/pipeline_service.py` — refactored to a single row-based `_run_to_response` path shared by sync run, async enqueue, and the poll endpoint; new `enqueue_profile_run` (creates a `queued` run, submits to the queue, returns immediately), `execute_run` (worker: `queued → running → terminal`, owns its own sessions, always records a terminal status even on unexpected failure), and `get_run_response`
- [x] `api/routes/runs.py` — `POST /profiles/{uuid}/run?async=true` → **HTTP 202** `status: "queued"`; new `GET /api/v1/runs/{run_uuid}` poll endpoint (404 on unknown)
- [x] `api/app.py` — lifespan starts the worker pool on startup and drains it (`wait=True`) on shutdown
- [x] Frontend — `Background (async)` toggle in the run panel; enqueues then polls `GET /runs/{uuid}` with live `queued → running → completed` feedback
- [x] Tests: `tests/test_async_runs.py` (8 tests) — 202 + `queued` returned immediately, background completion via polling, persisted queries/recs visible through the profile endpoints, sync run still 200, 404 unknown run, 404 async run for unknown profile, queue executes its worker, queue swallows worker exceptions
- [x] Verified: black clean (79 files), ruff clean, mypy clean (61 files), **pytest 210 passed** (+8); live `POST /run?async=true` → 202 `queued`, poll → `completed` (planned=7, extracted=4); `/api/v1/runs/{run_uuid}` present in OpenAPI (now 8 paths); sync `POST /run` still 200; frontend `npm run build` clean
- [x] Commit: `feat(runs): async background execution + run status polling (bonus)`

### ✅ Phase 13 — Observability visualization + live failure simulation

> Makes the graded-but-previously-invisible engineering signals (DAG path, per-node metrics, resilience
> fallback) inspectable from the API and the dashboard, so a reviewer never has to take them on faith.

- [x] `db/models.py` — `Run.metrics` JSON column persisting the per-run observability summary
- [x] `schemas/run.py` — `NodeMetricSchema` + `ObservabilitySchema`; `RunResponse.observability`
- [x] `observability/metrics.py` + `graph/nodes.py` — retries counted and attributed to the node during which they occur (`record_retry`/`take_pending_retries`)
- [x] `graph/build.py` + `graph/dependencies.py` — client `on_retry` wired into run metrics; `run_pipeline(mock_hook=...)` for live fault injection
- [x] `services/pipeline_service.py` — persists `metrics.summary()`; `_observability_from_row`; `run_profile_pipeline(simulate=)` + `_simulate_hook(outage|degraded)`
- [x] `api/routes/runs.py` — `POST /run?simulate=outage|degraded` (synchronous, injected failure)
- [x] Frontend — `GraphView` (executed DAG path + per-node badges), `ObservabilityPanel` (§3: totals + trace table + correlation id), and a **Resilience demo** row (Simulate partial/total failure) in the run panel
- [x] Tests: `tests/test_observability_api.py` (5) — observability shape/order/success-rate/api-calls, persisted + pollable, `simulate=outage`→`failed` via `fallback`, `simulate=degraded`→`partial`, bad mode → 422
- [x] Verified: black clean (80 files), ruff clean, mypy clean (61 files), **pytest 215 passed** (+5); live outage sim → `failed`, `total_retries=4` attributed to `retrieve_data`; frontend `npm run build` clean (27 modules)
- [x] Commit: `feat(observability): expose per-run node metrics + DAG/metrics dashboard + live failure simulation`

---

## Bonuses (both PDF-named bonuses delivered)

| Bonus (spec section)                                       | Status | Proof (file/test)                                                                                                        |
| ---------------------------------------------------------- | ------ | ------------------------------------------------------------------------------------------------------------------------ |
| Circuit breaker for a repeatedly-failing dependency (§3.5) | ✅     | `app/resilience/circuit_breaker.py` + `tests/test_resilience.py`                                                         |
| Async / background run processing + task queue (§4.2)      | ✅     | `app/services/run_queue.py` + `app/services/pipeline_service.py` + `app/api/routes/runs.py` + `tests/test_async_runs.py` |

---

## Requirement traceability (mirror of PLAN §0)

Each row is done only when a file/test proves it.

| #   | Requirement                                               | Status | Proof (file/test)                                                                                              |
| --- | --------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------- |
| R1  | Explicit LangGraph DAG, named nodes/edges                 | ✅     | `app/graph/build.py` + `tests/test_graph.py`                                                                   |
| R2  | Conditional routing + fallback path                       | ✅     | `app/graph/edges.py` + `tests/test_graph.py`                                                                   |
| R3  | DAG diagram in README                                     | ✅     | `README.md` (ASCII architecture + Mermaid DAG flow)                                                            |
| R4  | 5 atomic single-responsibility agents                     | ✅     | `app/agents/{planner,retrieval,extraction,analysis,report}.py` + `tests/test_agents.py`                        |
| R5  | No agent does two jobs                                    | ✅     | typed contracts in `app/agents/types.py` + per-agent isolation tests                                           |
| R6  | Tools defined with Pydantic/JSON schemas                  | ✅     | `app/tools/schemas.py` + `tests/test_tools.py`                                                                 |
| R7  | LLM decides tool + args; validate before real call        | ✅     | `app/tools/base.py` (validate-before-call) + `tests/test_tools.py`                                             |
| R8  | Graceful handling of malformed/partial tool args          | ✅     | `app/tools/base.py` + `tests/test_tools.py`                                                                    |
| R9  | DataForSEO integration w/ documented mode flag            | ✅     | `app/integrations/dataforseo/client.py` + `tests/test_tools.py`                                                |
| R10 | One tool per logical API call                             | ✅     | `app/tools/dataforseo_tools.py` + `tests/test_tools.py`                                                        |
| R11 | Retry w/ exponential backoff + jitter                     | ✅     | `app/resilience/retry.py` + `tests/test_resilience.py`                                                         |
| R12 | Retryable vs non-retryable classification                 | ✅     | `app/resilience/errors.py` + `tests/test_resilience.py`                                                        |
| R13 | Sane timeouts on all external calls                       | ✅     | `app/integrations/dataforseo/client.py` (httpx connect+read `Timeout`)                                         |
| R14 | Graceful degradation / partial results + error flag       | ✅     | `app/graph/nodes.py` (fallback + status) + `app/graph/edges.py` + `tests/test_graph.py`                        |
| R15 | Circuit breaker (bonus)                                   | ✅     | `app/resilience/circuit_breaker.py` + `tests/test_resilience.py`                                               |
| R16 | Structured JSON logs per node                             | ✅     | `app/observability/logging.py` + `tests/test_observability.py`                                                 |
| R17 | Trace across run (correlation ID)                         | ✅     | `app/observability/tracing.py` + `tests/test_observability.py`                                                 |
| R18 | Metrics: latency, success/fail, API call counts           | ✅     | `app/observability/metrics.py` + `tests/test_observability.py`                                                 |
| R19 | README: production observability roadmap                  | ✅     | `README.md` (§ Resilience & observability → production roadmap)                                                |
| R20 | `POST /api/v1/profiles` → 201 shape                       | ✅     | `app/api/routes/profiles.py` + `app/services/profile_service.py` + `tests/test_api.py`                         |
| R21 | `GET /api/v1/profiles/{uuid}` + summary stats             | ✅     | `app/api/routes/profiles.py` + `app/services/profile_service.py` + `tests/test_api.py`                         |
| R22 | `POST /api/v1/profiles/{uuid}/run` full DAG               | ✅     | `app/api/routes/runs.py` + `app/services/pipeline_service.py` + `tests/test_api.py`                            |
| R23 | `GET .../queries` filters + pagination + fields           | ✅     | `app/api/routes/queries.py` + `app/services/profile_service.py` + `tests/test_api.py`                          |
| R24 | `GET .../recommendations` + fields                        | ✅     | `app/api/routes/recommendations.py` + `app/services/profile_service.py` + `test_api.py`                        |
| R25 | `POST /api/v1/queries/{uuid}/recheck` partial re-run      | ✅     | `app/api/routes/queries.py` + `app/services/recheck_service.py` + `tests/test_api.py`                          |
| R26 | Persistence: profiles/runs/queries/recommendations        | ✅     | `app/db/models.py` + `db/repositories.py` + `tests/test_persistence.py`                                        |
| R27 | README (architecture, setup, agents, failures, obs, ...)  | ✅     | `README.md` (all sections incl. worked failure example + log excerpts + limitations)                           |
| R28 | Tests: happy, failure+retry/fallback, tool-arg validation | ✅     | `tests/test_happy_path.py`, `test_failure_retry.py`, `test_fallback_degradation.py`, `test_tool_validation.py` |
| R29 | `.env.example` documenting config                         | ✅     | `.env.example`                                                                                                 |
| R30 | Single-command run + clear git history                    | ✅     | `Makefile` (`make install && make run`) + phase-based commit history                                           |
| R31 | opportunity_score formula documented                      | ✅     | `app/agents/analysis.py` (`opportunity_score`) + `tests/test_agents.py` + README                               |
| R32 | total tokens used surfaced                                | ✅     | `app/llm/base.py` (`total_tokens`) + `app/llm/client.py` + `tests/test_llm.py`                                 |

**Done:** 32 / 32 — every graded requirement is satisfied with a file/test pointer. R3, R19, R27, and R30
landed with the Phase 10 README polish; R30's clean, phase-based git history accumulated across every
phase commit.

---

## Verification snapshot (through Phase 12 — all phases + both bonuses)

| Check             | Command                     | Result                                                                |
| ----------------- | --------------------------- | --------------------------------------------------------------------- |
| Lint              | `make lint`                 | ✅ clean                                                              |
| Format            | `black --check`             | ✅ clean (80 files)                                                   |
| Type-check        | `make typecheck`            | ✅ clean (61 app files)                                               |
| Tests             | `make test`                 | ✅ 215 passed (spec happy/failure/validation + async + observability) |
| API boots         | `python -m app` → `/health` | ✅ 200 + `/docs` 200 + all 7 `/api/v1` paths in OpenAPI               |
| Async bonus       | `POST /run?async=true`      | ✅ 202 `queued` → poll `GET /runs/{uuid}` → `completed`               |
| Observability     | run `observability` block   | ✅ per-node latency/success/api-calls/retries persisted + returned    |
| Failure sim       | `POST /run?simulate=outage` | ✅ `failed` via `fallback`, retries attributed, breaker trips         |
| API contracts     | `tests/test_api.py`         | ✅ 201/200/404/422, shapes, sort, filters, pagination, recheck        |
| DB schema         | `init_db()`                 | ✅ 4 tables created (lifespan + direct)                               |
| Observability     | JSON logs + redaction       | ✅ corr-id + secrets scrubbed                                         |
| Resilience        | retry / classify / CB       | ✅ backoff+jitter, fast-fail, breaker trips                           |
| DataForSEO tools  | mock / live / stub          | ✅ validate-before-call, retry+breaker, timeouts                      |
| LLM layer         | mock / openai / tokens      | ✅ tool binding, token accounting, resilient retry                    |
| Agents (5 atomic) | chained keyless demo        | ✅ plan→retrieve→extract→analyze→report, per-agent JSON logs          |
| Graph (DAG)       | `run_pipeline` demo         | ✅ completed / partial / failed routing, fallback, run metrics        |
| End-to-end run    | live `POST /run` (mock)     | ✅ `completed`, planned=7, extracted=4, sorted top insights           |
| Frontend build    | `npm run build`             | ✅ tsc (strict) + vite clean, 25 modules; full dashboard              |
| Frontend ↔ API    | `make run-frontend`         | ✅ dev server serves + reaches API (health polling in logs)           |

---

## How to update this file

At the end of each phase: check off the phase's items, flip the relevant traceability rows to ✅
(with a proof pointer), bump **Current phase** / **Overall progress** / **Last updated**, and refresh
the verification snapshot if commands changed. Keep it honest — a row is done only when a file or test
proves it.
