# Build Status Tracker

> Single source of truth for **what is done** and **what is left**. Updated at the end of every phase.
> Companion docs: [`PLAN.md`](./PLAN.md) (engineering plan) · [`WHAT_TO_BUILD.md`](./WHAT_TO_BUILD.md) (plain-English scope).

**Last updated:** 2026-09-06
**Current phase:** Phase 4 — DataForSEO integration + tools (next)
**Overall progress:** Phases 0–3 of 11 complete (foundation + persistence + observability + resilience ✅)

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

### ☐ Phase 4 — DataForSEO integration + tools

- [ ] `integrations/dataforseo/client.py` (httpx, timeouts, mode switch, retry + breaker)
- [ ] `integrations/dataforseo/endpoints.py` + realistic `mock/` fixtures
- [ ] `tools/schemas.py`, `tools/base.py` (validating wrapper), `tools/dataforseo_tools.py`
- [ ] Tests: tool-arg validation, mock round-trip, injected failure → classified error
- [ ] Commit: `feat(tools): typed DataForSEO tools + validating wrapper + mock client`

### ☐ Phase 5 — LLM layer

- [ ] `llm/client.py` (factory, tool binding, token-usage callback)
- [ ] `llm/prompts.py` (per-agent system prompts)
- [ ] Mock LLM for deterministic tests
- [ ] Commit: `feat(llm): provider client, tool binding, token accounting`

### ☐ Phase 6 — Agents (the 5, atomic)

- [ ] `agents/planner.py`
- [ ] `agents/retrieval.py`
- [ ] `agents/extraction.py`
- [ ] `agents/analysis.py` (+ opportunity_score formula)
- [ ] `agents/report.py`
- [ ] Per-agent isolation unit tests
- [ ] Commit: `feat(agents): 5 atomic single-responsibility agents`

### ☐ Phase 7 — Graph assembly

- [ ] `graph/state.py` (shared typed state)
- [ ] `graph/nodes.py` (wrap agents + tracing/metrics)
- [ ] `graph/edges.py` (conditional routing + fallback)
- [ ] `graph/build.py` (compile StateGraph)
- [ ] Integration test: happy path end-to-end on mocks
- [ ] Commit: `feat(graph): LangGraph DAG with conditional routing + fallback`

### ☐ Phase 8 — Services + API

- [ ] `services/{profile_service,pipeline_service,recheck_service}.py`
- [ ] `api/errors.py`, `api/deps.py`, `schemas/*`
- [ ] `routes/{profiles,runs,queries,recommendations}.py`
- [ ] Commit: `feat(api): FastAPI endpoints + services wiring`

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

| #   | Requirement                                               | Status | Proof (file/test)                                                       |
| --- | --------------------------------------------------------- | ------ | ----------------------------------------------------------------------- |
| R1  | Explicit LangGraph DAG, named nodes/edges                 | ☐      | `app/graph/build.py`                                                    |
| R2  | Conditional routing + fallback path                       | ☐      | `app/graph/edges.py`                                                    |
| R3  | DAG diagram in README                                     | ☐      | `README.md`                                                             |
| R4  | 5 atomic single-responsibility agents                     | ☐      | `app/agents/*.py`                                                       |
| R5  | No agent does two jobs                                    | ☐      | node contracts + tests                                                  |
| R6  | Tools defined with Pydantic/JSON schemas                  | ☐      | `app/tools/schemas.py`                                                  |
| R7  | LLM decides tool + args; validate before real call        | ☐      | `app/tools/base.py`                                                     |
| R8  | Graceful handling of malformed/partial tool args          | ☐      | `app/tools/base.py`                                                     |
| R9  | DataForSEO integration w/ documented mode flag            | ☐      | `app/integrations/dataforseo/`                                          |
| R10 | One tool per logical API call                             | ☐      | `app/tools/dataforseo_tools.py`                                         |
| R11 | Retry w/ exponential backoff + jitter                     | ✅     | `app/resilience/retry.py` + `tests/test_resilience.py`                  |
| R12 | Retryable vs non-retryable classification                 | ✅     | `app/resilience/errors.py` + `tests/test_resilience.py`                 |
| R13 | Sane timeouts on all external calls                       | 🔄     | config in `app/config.py` (wired into httpx client in Phase 4)          |
| R14 | Graceful degradation / partial results + error flag       | ☐      | fallback node + state                                                   |
| R15 | Circuit breaker (bonus)                                   | ✅     | `app/resilience/circuit_breaker.py` + `tests/test_resilience.py`        |
| R16 | Structured JSON logs per node                             | ✅     | `app/observability/logging.py` + `tests/test_observability.py`          |
| R17 | Trace across run (correlation ID)                         | ✅     | `app/observability/tracing.py` + `tests/test_observability.py`          |
| R18 | Metrics: latency, success/fail, API call counts           | ✅     | `app/observability/metrics.py` + `tests/test_observability.py`          |
| R19 | README: production observability roadmap                  | ☐      | `README.md`                                                             |
| R20 | `POST /api/v1/profiles` → 201 shape                       | ☐      | `app/api/routes/profiles.py`                                            |
| R21 | `GET /api/v1/profiles/{uuid}` + summary stats             | ☐      | `app/api/routes/profiles.py`                                            |
| R22 | `POST /api/v1/profiles/{uuid}/run` full DAG               | ☐      | `app/api/routes/runs.py`                                                |
| R23 | `GET .../queries` filters + pagination + fields           | ☐      | `app/api/routes/queries.py`                                             |
| R24 | `GET .../recommendations` + fields                        | ☐      | `app/api/routes/recommendations.py`                                     |
| R25 | `POST /api/v1/queries/{uuid}/recheck` partial re-run      | ☐      | `app/api/routes/queries.py`                                             |
| R26 | Persistence: profiles/runs/queries/recommendations        | ✅     | `app/db/models.py` + `db/repositories.py` + `tests/test_persistence.py` |
| R27 | README (architecture, setup, agents, failures, obs, ...)  | ☐      | `README.md`                                                             |
| R28 | Tests: happy, failure+retry/fallback, tool-arg validation | ☐      | `tests/`                                                                |
| R29 | `.env.example` documenting config                         | ✅     | `.env.example`                                                          |
| R30 | Single-command run + clear git history                    | 🔄     | `Makefile`, commits                                                     |
| R31 | opportunity_score formula documented                      | ☐      | `app/agents/analysis.py` + README                                       |
| R32 | total tokens used surfaced                                | ☐      | token callback in LLM client                                            |

**Done:** 8 / 32 (+2 in progress) — feature rows flip as Phases 4–10 land.

---

## Verification snapshot (through Phase 3)

| Check          | Command                | Result                                      |
| -------------- | ---------------------- | ------------------------------------------- |
| Lint           | `make lint`            | ✅ clean                                    |
| Format         | `black --check`        | ✅ clean (32 files)                         |
| Type-check     | `make typecheck`       | ✅ clean (27 files)                         |
| Tests          | `make test`            | ✅ 56 passed                                |
| API boots      | `make run` → `/health` | ✅ 200 + `/docs`                            |
| DB schema      | `init_db()`            | ✅ 4 tables created                         |
| Observability  | JSON logs + redaction  | ✅ corr-id + secrets scrubbed               |
| Resilience     | retry / classify / CB  | ✅ backoff+jitter, fast-fail, breaker trips |
| Frontend build | `npm run build`        | ✅ compiles                                 |

---

## How to update this file

At the end of each phase: check off the phase's items, flip the relevant traceability rows to ✅
(with a proof pointer), bump **Current phase** / **Overall progress** / **Last updated**, and refresh
the verification snapshot if commands changed. Keep it honest — a row is done only when a file or test
proves it.
