# Build Status Tracker

> Single source of truth for **what is done** and **what is left**. Updated at the end of every phase.
> Companion docs: [`PLAN.md`](./PLAN.md) (engineering plan) · [`WHAT_TO_BUILD.md`](./WHAT_TO_BUILD.md) (plain-English scope).

**Last updated:** 2026-09-06
**Current phase:** Phase 9 — Full test suite (next)
**Overall progress:** Phases 0–8 of 11 complete (foundation + persistence + observability + resilience + DataForSEO tools + LLM layer + 5 atomic agents + LangGraph DAG + FastAPI services & endpoints ✅)

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

### ☐ Phase 9 — Full test suite

- [ ] `test_happy_path.py`
- [ ] `test_failure_retry.py`
- [ ] `test_fallback_degradation.py`
- [ ] `test_tool_validation.py`
- [ ] `test_api_contracts.py`
- [ ] `test_opportunity_score.py`
- [ ] Commit: `test: happy path, failure+retry, fallback, tool validation, API contracts`

### ☐ Phase 10 — README + polish (graded deliverable)

- [ ] Full README: architecture, DAG diagram, setup, agents, failures example, observability excerpt, limitations, API reference
- [ ] Flip all traceability rows to ✅; final lint/type/test pass
- [ ] Commit: `docs: README with architecture, DAG diagram, failure & observability examples`

### ☐ Phase 11 — Responsive dashboard frontend (beyond-spec)

- [ ] Profile form
- [ ] Run pipeline + live status
- [ ] Run summary
- [ ] Queries table (sort/filter/paginate + recheck)
- [ ] Insights & recommendations
- [ ] Report view + trace/log excerpt
- [ ] Empty/loading/error states everywhere
- [ ] Commit: `feat(frontend): responsive React dashboard (beyond-spec extra)`

---

## Requirement traceability (mirror of PLAN §0)

Each row is done only when a file/test proves it.

| #   | Requirement                                               | Status | Proof (file/test)                                                                       |
| --- | --------------------------------------------------------- | ------ | --------------------------------------------------------------------------------------- |
| R1  | Explicit LangGraph DAG, named nodes/edges                 | ✅     | `app/graph/build.py` + `tests/test_graph.py`                                            |
| R2  | Conditional routing + fallback path                       | ✅     | `app/graph/edges.py` + `tests/test_graph.py`                                            |
| R3  | DAG diagram in README                                     | ☐      | `README.md`                                                                             |
| R4  | 5 atomic single-responsibility agents                     | ✅     | `app/agents/{planner,retrieval,extraction,analysis,report}.py` + `tests/test_agents.py` |
| R5  | No agent does two jobs                                    | ✅     | typed contracts in `app/agents/types.py` + per-agent isolation tests                    |
| R6  | Tools defined with Pydantic/JSON schemas                  | ✅     | `app/tools/schemas.py` + `tests/test_tools.py`                                          |
| R7  | LLM decides tool + args; validate before real call        | ✅     | `app/tools/base.py` (validate-before-call) + `tests/test_tools.py`                      |
| R8  | Graceful handling of malformed/partial tool args          | ✅     | `app/tools/base.py` + `tests/test_tools.py`                                             |
| R9  | DataForSEO integration w/ documented mode flag            | ✅     | `app/integrations/dataforseo/client.py` + `tests/test_tools.py`                         |
| R10 | One tool per logical API call                             | ✅     | `app/tools/dataforseo_tools.py` + `tests/test_tools.py`                                 |
| R11 | Retry w/ exponential backoff + jitter                     | ✅     | `app/resilience/retry.py` + `tests/test_resilience.py`                                  |
| R12 | Retryable vs non-retryable classification                 | ✅     | `app/resilience/errors.py` + `tests/test_resilience.py`                                 |
| R13 | Sane timeouts on all external calls                       | ✅     | `app/integrations/dataforseo/client.py` (httpx connect+read `Timeout`)                  |
| R14 | Graceful degradation / partial results + error flag       | ✅     | `app/graph/nodes.py` (fallback + status) + `app/graph/edges.py` + `tests/test_graph.py` |
| R15 | Circuit breaker (bonus)                                   | ✅     | `app/resilience/circuit_breaker.py` + `tests/test_resilience.py`                        |
| R16 | Structured JSON logs per node                             | ✅     | `app/observability/logging.py` + `tests/test_observability.py`                          |
| R17 | Trace across run (correlation ID)                         | ✅     | `app/observability/tracing.py` + `tests/test_observability.py`                          |
| R18 | Metrics: latency, success/fail, API call counts           | ✅     | `app/observability/metrics.py` + `tests/test_observability.py`                          |
| R19 | README: production observability roadmap                  | ☐      | `README.md`                                                                             |
| R20 | `POST /api/v1/profiles` → 201 shape                       | ✅     | `app/api/routes/profiles.py` + `app/services/profile_service.py` + `tests/test_api.py`  |
| R21 | `GET /api/v1/profiles/{uuid}` + summary stats             | ✅     | `app/api/routes/profiles.py` + `app/services/profile_service.py` + `tests/test_api.py`  |
| R22 | `POST /api/v1/profiles/{uuid}/run` full DAG               | ✅     | `app/api/routes/runs.py` + `app/services/pipeline_service.py` + `tests/test_api.py`     |
| R23 | `GET .../queries` filters + pagination + fields           | ✅     | `app/api/routes/queries.py` + `app/services/profile_service.py` + `tests/test_api.py`   |
| R24 | `GET .../recommendations` + fields                        | ✅     | `app/api/routes/recommendations.py` + `app/services/profile_service.py` + `test_api.py` |
| R25 | `POST /api/v1/queries/{uuid}/recheck` partial re-run      | ✅     | `app/api/routes/queries.py` + `app/services/recheck_service.py` + `tests/test_api.py`   |
| R26 | Persistence: profiles/runs/queries/recommendations        | ✅     | `app/db/models.py` + `db/repositories.py` + `tests/test_persistence.py`                 |
| R27 | README (architecture, setup, agents, failures, obs, ...)  | ☐      | `README.md`                                                                             |
| R28 | Tests: happy, failure+retry/fallback, tool-arg validation | ☐      | `tests/`                                                                                |
| R29 | `.env.example` documenting config                         | ✅     | `.env.example`                                                                          |
| R30 | Single-command run + clear git history                    | 🔄     | `Makefile`, commits                                                                     |
| R31 | opportunity_score formula documented                      | ✅     | `app/agents/analysis.py` (`opportunity_score`) + `tests/test_agents.py` + README        |
| R32 | total tokens used surfaced                                | ✅     | `app/llm/base.py` (`total_tokens`) + `app/llm/client.py` + `tests/test_llm.py`          |

**Done:** 27 / 32 (+1 in progress) — remaining rows (R3, R19, R27, R28, R30) flip as Phases 9–10 land.

---

## Verification snapshot (through Phase 8)

| Check             | Command                     | Result                                                         |
| ----------------- | --------------------------- | -------------------------------------------------------------- |
| Lint              | `make lint`                 | ✅ clean                                                       |
| Format            | `black --check`             | ✅ clean (70 files)                                            |
| Type-check        | `make typecheck`            | ✅ clean (60 files)                                            |
| Tests             | `make test`                 | ✅ 141 passed                                                  |
| API boots         | `python -m app` → `/health` | ✅ 200 + `/docs` 200 + all 6 `/api/v1` paths in OpenAPI        |
| API contracts     | `tests/test_api.py`         | ✅ 201/200/404/422, shapes, sort, filters, pagination, recheck |
| DB schema         | `init_db()`                 | ✅ 4 tables created (lifespan + direct)                        |
| Observability     | JSON logs + redaction       | ✅ corr-id + secrets scrubbed                                  |
| Resilience        | retry / classify / CB       | ✅ backoff+jitter, fast-fail, breaker trips                    |
| DataForSEO tools  | mock / live / stub          | ✅ validate-before-call, retry+breaker, timeouts               |
| LLM layer         | mock / openai / tokens      | ✅ tool binding, token accounting, resilient retry             |
| Agents (5 atomic) | chained keyless demo        | ✅ plan→retrieve→extract→analyze→report, per-agent JSON logs   |
| Graph (DAG)       | `run_pipeline` demo         | ✅ completed / partial / failed routing, fallback, run metrics |
| End-to-end run    | live `POST /run` (mock)     | ✅ `completed`, planned=7, extracted=4, sorted top insights    |
| Frontend build    | `npm run build`             | ✅ compiles                                                    |

---

## How to update this file

At the end of each phase: check off the phase's items, flip the relevant traceability rows to ✅
(with a proof pointer), bump **Current phase** / **Overall progress** / **Last updated**, and refresh
the verification snapshot if commands changed. Keep it honest — a row is done only when a file or test
proves it.
