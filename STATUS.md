# Build Status Tracker

> Single source of truth for **what is done** and **what is left**. Updated at the end of every phase.
> Companion docs: [`PLAN.md`](./PLAN.md) (engineering plan) · [`WHAT_TO_BUILD.md`](./WHAT_TO_BUILD.md) (plain-English scope).

**Last updated:** 2026-09-06
**Current phase:** Phase 2 — Observability core (next)
**Overall progress:** Phases 0–1 of 11 complete (foundation + persistence ✅)

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

### ☐ Phase 2 — Observability core

- [ ] `observability/logging.py` (structured JSON + secret redaction)
- [ ] `observability/tracing.py` (correlation-id context)
- [ ] `observability/metrics.py` (per-run metrics collector)
- [ ] Commit: `feat(obs): logging, tracing, metrics`

### ☐ Phase 3 — Resilience core

- [ ] `resilience/errors.py` (retryable vs non-retryable taxonomy + `classify`)
- [ ] `resilience/retry.py` (exponential backoff + jitter)
- [ ] `resilience/circuit_breaker.py` (closed/open/half-open)
- [ ] Unit tests: classification, retry counting, breaker transitions
- [ ] Commit: `feat(resilience): retry/backoff/jitter, classification, breaker`

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
| R11 | Retry w/ exponential backoff + jitter                     | ☐      | `app/resilience/retry.py`                                               |
| R12 | Retryable vs non-retryable classification                 | ☐      | `app/resilience/errors.py`                                              |
| R13 | Sane timeouts on all external calls                       | ☐      | HTTP client config                                                      |
| R14 | Graceful degradation / partial results + error flag       | ☐      | fallback node + state                                                   |
| R15 | Circuit breaker (bonus)                                   | ☐      | `app/resilience/circuit_breaker.py`                                     |
| R16 | Structured JSON logs per node                             | ☐      | `app/observability/logging.py`                                          |
| R17 | Trace across run (correlation ID)                         | ☐      | `app/observability/tracing.py`                                          |
| R18 | Metrics: latency, success/fail, API call counts           | ☐      | `app/observability/metrics.py`                                          |
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

**Done:** 2 / 32 (+1 in progress) — feature rows flip as Phases 2–10 land.

---

## Verification snapshot (through Phase 1)

| Check          | Command                | Result              |
| -------------- | ---------------------- | ------------------- |
| Lint           | `make lint`            | ✅ clean            |
| Format         | `black --check`        | ✅ clean (24 files) |
| Type-check     | `make typecheck`       | ✅ clean (21 files) |
| Tests          | `make test`            | ✅ 6 passed         |
| API boots      | `make run` → `/health` | ✅ 200 + `/docs`    |
| DB schema      | `init_db()`            | ✅ 4 tables created |
| Frontend build | `npm run build`        | ✅ compiles         |

---

## How to update this file

At the end of each phase: check off the phase's items, flip the relevant traceability rows to ✅
(with a proof pointer), bump **Current phase** / **Overall progress** / **Last updated**, and refresh
the verification snapshot if commands changed. Keep it honest — a row is done only when a file or test
proves it.
