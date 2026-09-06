# Agentic Search Intelligence System

A production-minded **multi-agent pipeline** that answers questions about how a brand shows up in
search engines and AI answers. It is built as an explicit **LangGraph DAG** of five atomic agents
(Planner → Retrieval → Extraction → Analysis → Report), exposed through a **FastAPI JSON API** with
persistence, resilience, and observability.

Built for the _AI Agent Engineer — Technical Assessment (v2.0)_.

> **Build status:** complete. Persistence, observability, resilience, DataForSEO tools, the LLM layer,
> the five atomic agents, the LangGraph DAG, the full FastAPI service + endpoint layer, the complete
> spec-mandated test suite (202 tests green), and the beyond-spec React dashboard are all implemented and
> verified — `make check` is clean (ruff + mypy + 202 tests) and a live `POST /run` returns `completed`
> in mock mode with zero credentials. See **[`STATUS.md`](./STATUS.md)** for the phase-by-phase record.

---

## Table of contents

- [What it does](#what-it-does)
- [Architecture](#architecture)
- [The five agents](#the-five-agents)
- [Tech stack](#tech-stack)
- [Project structure](#project-structure)
- [Getting started](#getting-started)
- [Configuration](#configuration)
- [DataForSEO modes](#dataforseo-modes)
- [opportunity_score](#opportunity_score)
- [API overview](#api-overview)
- [Resilience & observability](#resilience--observability)
- [Testing](#testing)
- [Frontend (beyond-spec)](#frontend-beyond-spec)
- [Known limitations & what I'd improve](#known-limitations--what-id-improve)
- [Documentation index](#documentation-index)

---

## What it does

Given a brand profile (name, domain, industry, competitors), a pipeline run:

1. **Plans** which searches / API calls are needed to answer the question.
2. **Retrieves** raw data from DataForSEO via validated tool calls.
3. **Extracts / normalizes** messy API responses into a clean schema.
4. **Analyzes** the clean data into insights, opportunity scores, and recommendations.
5. **Reports** a final structured JSON output plus a human-readable summary.

Each step is its **own agent** with a single responsibility, wired as a directed acyclic graph with
conditional routing and a fallback path so the pipeline degrades gracefully instead of crashing.

For the full plain-English scope, read **[`WHAT_TO_BUILD.md`](./WHAT_TO_BUILD.md)**.

---

## Architecture

```
   HTTP (JSON)          ┌──────────────────────────────────────────┐
  ──────────────▶       │            FastAPI application            │
                        │   routes → services → LangGraph runner    │
                        └───────────────┬──────────────────────────┘
                                        │ invokes
                                        ▼
                        ┌──────────────────────────────────────────┐
                        │          LangGraph DAG (compiled)         │
                        │  Planner → Retrieval → Extract →          │
                        │  Analyze → Report   (+ fallback edges)    │
                        └───────────────┬──────────────────────────┘
        tools (validated)               │                observability
                 ▼                      ▼                      ▼
    ┌────────────────────┐   ┌────────────────┐   ┌────────────────────┐
    │ DataForSEO client  │   │  Persistence   │   │ logs/trace/metrics │
    │(live | mock | stub)│   │ (SQLite/SQLA)  │   │  (JSON, corr-id)   │
    └────────────────────┘   └────────────────┘   └────────────────────┘
```

### DAG flow

```mermaid
flowchart TD
    START([POST /run]) --> P[plan_queries<br/>Query Planner]
    P -->|valid plan, >=1 call| R[retrieve_data<br/>Retrieval Agent]
    P -->|empty/invalid plan| F[fallback]
    R -->|usable results| N[normalize_data<br/>Extraction Agent]
    R -->|all retrieval failed| F
    N -->|extracted > 0| A[analyze_data<br/>Analysis Agent]
    N -->|nothing normalized| F
    A --> RP[build_report<br/>Report Agent]
    F --> RP
    RP --> END([Response: status + report])
```

The full layered design, data model, and rationale live in **[`PLAN.md`](./PLAN.md)**.

---

## The five agents

Each agent does exactly one job — combining them into "do-everything" agents is explicitly avoided.

| Agent                          | Its one job                                                         |
| ------------------------------ | ------------------------------------------------------------------- |
| **Query Planner**              | Decide which searches / API calls are needed. (Never fetches.)      |
| **Search / Retrieval Agent**   | Execute planned tool calls against DataForSEO. (Never summarizes.)  |
| **Extraction / Normalization** | Turn raw API JSON into a clean schema. (Never scores.)              |
| **Analysis / Synthesis**       | Reason over clean data → insights + scores. (Never formats output.) |
| **Report Agent**               | Assemble final JSON + human summary. (Never calls tools.)           |

---

## Tech stack

| Concern          | Choice                                      |
| ---------------- | ------------------------------------------- |
| Language         | Python 3.11+                                |
| Orchestration    | LangGraph + LangChain                       |
| LLM              | OpenAI via `langchain-openai`               |
| API              | FastAPI + Uvicorn                           |
| Validation       | Pydantic v2 / pydantic-settings             |
| Persistence      | SQLAlchemy 2.0 + SQLite                     |
| HTTP client      | httpx                                       |
| Resilience       | tenacity + custom retry / circuit breaker   |
| Logging          | structlog (JSON)                            |
| Testing          | pytest + pytest-asyncio + respx             |
| Tooling          | ruff + black + mypy                         |
| Frontend (extra) | React 19 + Vite 8 + TypeScript + Tailwind 4 |

---

## Project structure

```
.
├── app/
│   ├── __main__.py            # `python -m app` entrypoint
│   ├── config.py              # Pydantic Settings (env-driven)
│   ├── api/                   # FastAPI app factory, routes, deps, error mapping
│   ├── schemas/               # Pydantic request/response models
│   ├── services/              # orchestration: run the DAG, persist, summarize
│   ├── graph/                 # LangGraph state, nodes, edges, builder
│   ├── agents/                # the 5 atomic agents
│   ├── tools/                 # tool schemas + validating wrapper + DataForSEO tools
│   ├── integrations/dataforseo/  # httpx client, endpoints, mock fixtures
│   ├── llm/                   # LLM client + prompts
│   ├── resilience/            # error taxonomy, retry/backoff, circuit breaker
│   ├── observability/         # logging, tracing, metrics
│   └── db/                    # engine/session, models, repositories
├── tests/                     # happy path, failure/retry, fallback, tool validation
├── frontend/                  # responsive dashboard (beyond-spec)
├── PLAN.md                    # detailed engineering plan
├── WHAT_TO_BUILD.md           # plain-English scope
├── STATUS.md                  # live build-status tracker
├── pyproject.toml             # deps + ruff/black/mypy/pytest config
├── Makefile                   # single-command workflows
└── .env.example               # documented configuration
```

---

## Getting started

### Prerequisites

- Python **3.11+** (developed on 3.13)
- Node **20+** and npm (only for the optional frontend)
- No API keys required — the system runs fully in DataForSEO **mock mode** by default.

### Backend

```bash
make install     # create .venv and install the package + dev dependencies
make run         # start the API at http://localhost:8000
```

Then open:

- Health probe: <http://localhost:8000/health>
- Interactive API docs: <http://localhost:8000/docs>

Equivalent without Make: `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` then
`.venv/bin/python -m app`.

### Frontend (optional, beyond-spec)

```bash
make install-frontend    # npm install in frontend/
make run-frontend        # start Vite dev server at http://localhost:5173
```

---

## Configuration

Copy `.env.example` to `.env` and adjust as needed. Every key has a safe default, so `.env` is optional
in mock mode. Key groups:

- **LLM** — `OPENAI_API_KEY`, `LLM_MODEL`, `LLM_TEMPERATURE`
- **DataForSEO** — `DATAFORSEO_MODE` (`mock`|`live`|`stub`), `DATAFORSEO_LOGIN`, `DATAFORSEO_PASSWORD`, `DATAFORSEO_BASE_URL`
- **Timeouts & retries** — `HTTP_CONNECT_TIMEOUT_S`, `HTTP_READ_TIMEOUT_S`, `RETRY_MAX_ATTEMPTS`, `RETRY_BASE_DELAY_S`, `RETRY_MAX_DELAY_S`, `CIRCUIT_BREAKER_FAIL_THRESHOLD`, `CIRCUIT_BREAKER_COOLDOWN_S`
- **Scoring** — `OPP_WEIGHT_VOLUME`, `OPP_WEIGHT_DIFFICULTY`, `OPP_WEIGHT_GAP`, `OPP_VOLUME_CAP`
- **App** — `DATABASE_URL`, `LOG_LEVEL`, `API_HOST`, `API_PORT`, `LANGCHAIN_TRACING_V2`

Configuration is validated at startup (e.g. scoring weights must sum to `1.0`; `live` mode requires
DataForSEO credentials).

---

## DataForSEO modes

The integration supports three modes via `DATAFORSEO_MODE`:

- **`mock`** _(default)_ — deterministic local fixtures modeled on real DataForSEO response envelopes.
  No network, no credentials; tests are hermetic.
- **`live`** — calls the real DataForSEO API using Basic auth (`DATAFORSEO_LOGIN` / `DATAFORSEO_PASSWORD`).
- **`stub`** — minimal static stub responses.

One tool wraps exactly one logical API call.

---

## opportunity_score

A deterministic score in `[0, 1]` that rewards high-demand, low-difficulty keywords where the brand is
**not** currently visible:

```
volume_norm      = min(estimated_search_volume / OPP_VOLUME_CAP, 1)   # demand
difficulty_ease  = 1 - (competitive_difficulty / 100)                 # easier = better
visibility_gap   = 0.0 if domain_visible else 1.0                     # missing = opportunity

opportunity_score = round(
    OPP_WEIGHT_VOLUME * volume_norm
  + OPP_WEIGHT_DIFFICULTY * difficulty_ease
  + OPP_WEIGHT_GAP * visibility_gap, 4)
```

Weights (default `0.4 / 0.3 / 0.3`) and the volume cap are configurable and must sum to `1.0`.

---

## API overview

Base path: `/api/v1`. All responses are JSON; no authentication (out of scope).

| Method | Path                                       | Purpose                                   |
| ------ | ------------------------------------------ | ----------------------------------------- |
| POST   | `/profiles`                                | Register a brand/keyword profile          |
| GET    | `/profiles/{profile_uuid}`                 | Get a profile + summary stats             |
| POST   | `/profiles/{profile_uuid}/run`             | Run the full DAG (core endpoint)          |
| GET    | `/profiles/{profile_uuid}/queries`         | Discovered queries (filter/sort/paginate) |
| GET    | `/profiles/{profile_uuid}/recommendations` | Content recommendations                   |
| POST   | `/queries/{query_uuid}/recheck`            | Partial re-run for a single query         |

> All six endpoints are implemented and covered by contract tests (`tests/test_api.py`). The live,
> always-current contract is available at `/docs` once the server is running.

### Quick curl walkthrough

```bash
# 1. Create a profile (201)
curl -s -X POST http://localhost:8000/api/v1/profiles \
  -H "Content-Type: application/json" \
  -d '{"name":"Surfer SEO","domain":"surferseo.com","industry":"SEO Software","competitors":["clearscope.io"]}'

# 2. Run the pipeline (use the profile_uuid from step 1)
curl -s -X POST http://localhost:8000/api/v1/profiles/<profile_uuid>/run

# 3. Discovered queries, filtered + paginated
curl -s "http://localhost:8000/api/v1/profiles/<profile_uuid>/queries?min_score=0.5&status=not_visible&page=1&per_page=20"

# 4. Recommendations
curl -s http://localhost:8000/api/v1/profiles/<profile_uuid>/recommendations

# 5. Recheck a single query
curl -s -X POST http://localhost:8000/api/v1/queries/<query_uuid>/recheck
```

Degraded runs return HTTP 200 with `status: "partial"` / `"failed"` and `error_flag: true` (not an HTTP
error), so callers can always inspect partial results. Unknown UUIDs return `404`; invalid input `422` —
both in the uniform `{"error": {"code", "message", "details"}}` envelope.

---

## Resilience & observability

- **Resilience:** retry with exponential backoff + jitter for transient failures (timeouts, 429, 5xx),
  explicit retryable vs non-retryable classification, sane per-call timeouts, a circuit breaker, and a
  fallback graph path that returns partial results with an error flag instead of crashing.
- **Observability:** structured JSON logs per node (with secret redaction), a correlation ID to trace a
  run node-by-node, and a per-run metrics summary (latency, success/failure, API call counts, tokens).

### Worked example — simulating a failure

Failures are injected deterministically through the DataForSEO client's `mock_hook` seam, so you can
reproduce a dependency outage without any real network flakiness. The mandated test
`tests/test_fallback_degradation.py` wires a hook that raises `httpx.ConnectTimeout` on every call:

```python
def boom(path, payload):
    raise httpx.ConnectTimeout("simulated total outage")

client = DataForSeoClient(settings=settings, retry_policy=policy, mock_hook=boom)
```

What happens: each retrieval call is retried with exponential backoff + jitter, all retries are
exhausted, the circuit breaker trips to `open`, and the conditional edge after `retrieve_data` routes to
the deterministic `fallback` node instead of crashing. `build_report` still emits a report, and the run
is persisted with `status: "failed"`, `error_flag: true`, and a human-readable `degraded_reason`. A
_partial_ outage (only some calls fail) instead yields `status: "partial"` with analysis still running on
the surviving data. Run it with:

```bash
make test        # includes test_fallback_degradation.py (total + partial degradation)
```

### Sample log & trace excerpt

Every node emits a structured JSON line bound to a per-run `correlation_id`, and each run closes with a
`run.metrics` summary. A **healthy** run:

```json
{"node": "retrieve_data", "duration_ms": 0.376, "success": true, "event": "graph.node.finish", "correlation_id": "a0d0459035...", "level": "info", "timestamp": "2026-09-06T15:35:37Z"}
{"node": "build_report", "duration_ms": 0.17, "success": true, "event": "graph.node.finish", "correlation_id": "a0d0459035...", "level": "info", "timestamp": "2026-09-06T15:35:37Z"}
{"correlation_id": "a0d0459035...", "total_duration_ms": 14.767, "node_count": 5, "success_rate": 1.0, "total_api_calls": 7, "total_retries": 0, "total_tokens": 0, "event": "run.metrics", "level": "info"}
{"status": "completed", "error_flag": false, "event": "graph.run.finish", "correlation_id": "a0d0459035...", "level": "info"}
```

The same run under a **simulated total outage** — note the flow routes through `fallback` (skipping
`normalize_data`/`analyze_data`) and finishes `failed` without crashing:

```json
{"node": "retrieve_data", "duration_ms": 0.381, "success": true, "event": "graph.node.finish", "correlation_id": "6a328ca25a...", "level": "info"}
{"node": "fallback", "duration_ms": 0.03, "success": true, "event": "graph.node.finish", "correlation_id": "6a328ca25a...", "level": "info"}
{"node": "build_report", "duration_ms": 0.04, "success": true, "event": "graph.node.finish", "correlation_id": "6a328ca25a...", "level": "info"}
{"status": "failed", "error_flag": true, "event": "graph.run.finish", "correlation_id": "6a328ca25a...", "level": "info"}
# degraded_reason: "all retrieval calls failed (circuit_open, timeout)"
```

API keys and passwords are scrubbed by a redaction processor before anything is logged.

### Production observability roadmap

With more time, the in-process observability would graduate to:

- **OpenTelemetry** spans per node with an OTLP exporter, propagating the correlation ID as a trace ID
  across async workers.
- **Prometheus + Grafana** dashboards for latency histograms, success/failure rates, and API-call
  volume, with alerting on error-rate and latency SLOs.
- **LangSmith** (already gated behind `LANGCHAIN_TRACING_V2`) for step-level agent tracing.
- **Centralized log aggregation** (ELK / Loki) and a persistent metrics store, replacing the per-run
  in-memory collector.

---

## Testing

```bash
make test        # run the pytest suite
make lint        # ruff
make typecheck   # mypy
make check       # lint + typecheck + test
```

Tests are hermetic (mock LLM + mock DataForSEO + in-memory SQLite) and cover, at minimum, a happy-path
run, a simulated API failure that retries/falls back, and tool-call argument validation.

---

## Frontend (beyond-spec)

The assessment is backend-only; a responsive **React 19 + Vite + TypeScript + Tailwind** dashboard is
included as a deliberate extra to demonstrate end-to-end product sense. It is fully decoupled and talks to
the API over HTTP (base URL via `VITE_API_BASE_URL`), so the backend remains runnable and gradable
without it.

```bash
make install-frontend    # npm install in frontend/
make run-frontend        # Vite dev server at http://localhost:5173
```

The dashboard walks the whole pipeline in one page:

1. **Create a profile** — name, domain, industry, description, competitors (with inline validation).
2. **Run the pipeline** — one click triggers `POST /run`; a live spinner covers the run, then a status
   badge (`completed` / `partial` / `failed`) and a degraded-run banner appear.
3. **Run summary** — planned retrieval calls, extracted records, total tokens, insight count, plus the
   run and correlation IDs.
4. **Top insights** — scored, ranked queries with visibility badges and rationale.
5. **Queries table** — sorted by opportunity score, with `min_score` / visibility-status filters,
   pagination, and a per-row **recheck** button (`POST /recheck`).
6. **Recommendations** — content-type, priority, rationale, and target-keyword chips.
7. **Report** — the human-readable summary, a run-trace panel (correlation ID), and collapsible raw JSON.

Every panel has explicit loading, empty, and error states, and the layout is mobile-first, keyboard
navigable, and dark-mode aware. A live backend-connection badge polls `/health`.

---

## Known limitations & what I'd improve

- **DataForSEO defaults to mock mode.** Responses are deterministic fixtures modeled on the real
  `tasks[].result[]` envelope so the system runs and tests hermetically with zero credentials. `live`
  mode is fully wired (Basic auth, timeouts, retry + breaker); with a sandbox key I'd validate the real
  response shapes and expand the extraction mappers per endpoint.
- **Synchronous run endpoint.** A run takes 10–30s and blocks the request (the spec allows this). For
  production I'd move runs to a task queue (Celery/RQ) with a `GET /runs/{uuid}` status endpoint and,
  optionally, streaming progress.
- **SQLite persistence.** Ideal for the scope; the SQLAlchemy models port to Postgres with a URL change.
  I'd add Alembic migrations and connection pooling for a real deployment.
- **In-memory metrics.** The per-run collector is process-local; production would export to OpenTelemetry
  / Prometheus as described above.
- **LLM narrative is optional.** Scoring and extraction are fully deterministic; the LLM only adds
  qualitative prose, with a deterministic fallback so the pipeline never depends on model availability.

---

## Documentation index

| Doc                                      | Purpose                                         |
| ---------------------------------------- | ----------------------------------------------- |
| [`README.md`](./README.md)               | This file — overview, setup, architecture       |
| [`WHAT_TO_BUILD.md`](./WHAT_TO_BUILD.md) | Plain-English scope of the assessment           |
| [`PLAN.md`](./PLAN.md)                   | Detailed engineering plan + traceability matrix |
| [`STATUS.md`](./STATUS.md)               | Live build-status tracker                       |
