# What This Assessment Wants Us To Build (Plain English)

> This file explains, in simple language, **exactly what the assessment document is asking for**.
> No jargon-dumping — just what the thing is, why it exists, and what "done" looks like.
> Read this first. Then read `PLAN.md` for the detailed engineering plan.

---

## 1. The one-sentence version

Build a small but production-quality **AI system made of several cooperating "agents"** that takes a
plain-English question about how a brand shows up in search engines and AI answers, runs a
**multi-step pipeline** to gather and reason over real search data, and returns a **structured report**
plus recommendations — all exposed through a **JSON REST API**.

---

## 2. The story / why it exists

The company builds software that tells businesses **how visible they are inside AI answers**
(ChatGPT, Gemini, Perplexity, Google's AI Overviews) and **traditional search results**.

To do that, they run pipelines that:

1. Ask an external data provider (**DataForSEO**) for search/AI-visibility data,
2. Reason over the results,
3. Turn everything into clean, structured intelligence a customer can act on.

This assessment is a **miniature version of exactly that product**. They want to see how we:

- **Split responsibilities** between agents (not one giant do-everything blob),
- **Handle real-world API failures** (timeouts, rate limits, server errors),
- **Make the system observable** (logs, traces, metrics you could actually debug with).

> Their exact words: they care **much more** about how we structure agents, handle failure, and make
> the system observable than about a system that "just works once" on the happy path.

---

## 3. What the system actually does (end to end)

Imagine a user asks:

> "How does **Surfer SEO** show up in AI answers and search results for _'best project management software'_?"

The pipeline must:

1. **Plan** — Figure out which searches / API calls are needed to answer the question.
2. **Retrieve** — Call the right DataForSEO endpoints to get the raw data.
3. **Extract / Normalize** — Clean the messy raw API responses into a tidy, predictable schema.
4. **Analyze / Synthesize** — Reason over the clean data to produce insights (where the brand is
   visible, where it's missing, where the opportunities are).
5. **Report** — Assemble a final structured output: machine-readable **JSON** + a **human-readable summary**.

Each of these 5 steps must be its **own separate agent/node**. **This is graded heavily.**
For example, the agent that _fetches_ data must **not** also _summarize_ it.

---

## 4. The 5 agents and their one job each

| Agent                                | Its ONE job (nothing more)                                               |
| ------------------------------------ | ------------------------------------------------------------------------ |
| **Query Planner**                    | Read the user's question and decide which searches/API calls are needed. |
| **Search / Retrieval Agent(s)**      | Call the DataForSEO endpoint(s) using correctly-formed tool calls.       |
| **Extraction / Normalization Agent** | Turn raw API JSON into a clean, structured schema.                       |
| **Analysis / Synthesis Agent**       | Reason over the clean data to produce insights.                          |
| **Report Agent**                     | Assemble the final output (JSON + human-readable summary).               |

Combining these into fewer "do-everything" agents = losing points. Keep them atomic.

---

## 5. How the agents are wired together (the "DAG")

- The 5 agents are connected as an explicit **DAG** (Directed Acyclic Graph) using **LangGraph**
  (or an equivalent LangChain graph approach).
- It must **not** be a single long chain or a plain `if/else` script.
- Nodes and edges must be **clearly named**.
- There must be **conditional routing** — e.g., if a retrieval step fails validation, the graph should
  **route to a fallback path** instead of crashing.
- The README must include a **diagram** of this DAG (ASCII, Mermaid, or image).

Normal flow:

```
Query Planner -> Search/Retrieval -> Extraction/Normalization -> Analysis/Synthesis -> Report
```

Plus fallback branches when something goes wrong.

---

## 6. "Correct tool calling" (a big grading point)

- Tools must be defined with **proper schemas** (Pydantic models / JSON schema): accurate **types**,
  **descriptions**, and **required fields** — not just a prompt saying "please call the API".
- The **LLM decides** _when_ to call a tool and _with what arguments_.
- Our code must **validate the LLM's arguments BEFORE** making the real API call.
- If arguments are malformed or missing a required field, we handle it **gracefully** (no crash).
- Each DataForSEO call is wrapped behind its **own clean tool** — one tool per logical API call,
  **not** one giant "call DataForSEO" tool.

---

## 7. DataForSEO integration

- We use **DataForSEO's** API for the search / AI-visibility data.
- We are **allowed** to use any of these (and must state which one in the README):
  - a real free-tier / sandbox key, **or**
  - **mock responses** behind a clearly-marked flag, **or**
  - a documented **stub**.
- One tool = one logical API call.

---

## 8. Failure handling & resilience (a big grading point)

The system must survive real-world API problems:

- **Retry with exponential backoff + jitter** for transient failures (timeouts, 429 rate limits, 5xx errors).
- **Tell the difference** between:
  - **Retryable** errors (network / timeout / rate-limit) — retry these.
  - **Non-retryable** errors (bad request, auth failure) — don't retry, handle differently.
- **Sane timeouts** on every external call.
- After retries are exhausted, the DAG must **degrade gracefully** — route to a fallback node, or return
  **partial results with a clear error flag** — instead of crashing the whole pipeline.
- **Bonus:** a **circuit breaker** for a dependency that keeps failing.

---

## 9. Observability & monitoring (a big grading point)

- **Structured logging** (e.g., JSON logs) for **every node**: inputs (redacted where sensitive),
  outputs, duration, success/failure, retry count.
- **Tracing** across a run so one request can be followed node-by-node (LangSmith, OpenTelemetry, or a
  custom **correlation-ID** trace log are all fine).
- **Metrics**: per-node latency, success/failure rate, API call counts. A simple summary printed/logged
  at the end of a run is enough.
- README explains what we'd add for **production-grade** observability given more time.

---

## 10. The REST API we must build

All endpoints return **JSON**. **No authentication required** (out of scope).

### Profiles

- **`POST /api/v1/profiles`** — Register a brand/keyword profile (name, domain, industry, description,
  competitors). Returns `201` with a `profile_uuid`, status `created`, timestamp.
- **`GET /api/v1/profiles/{profile_uuid}`** — Get a profile plus summary stats: total DAG runs,
  most recent run status, average opportunity score across discovered queries.

### Pipeline

- **`POST /api/v1/profiles/{profile_uuid}/run`** — **The core endpoint.** Runs the full DAG in order
  (Planner → Retrieval → Extraction → Analysis → Report). Response includes:
  - a pipeline **run UUID**
  - **status**: `completed` / `failed` / `partial`
  - count of **retrieval calls planned** by the Query Planner
  - count of **records successfully extracted/normalized**
  - **top insights** (with relevance/opportunity scores)
  - the **final structured report** (JSON + human-readable summary)
  - **total tokens used** (if the provider gives it)
  - _Note:_ a run may take 10–30s. **Synchronous is fine.** Async (Celery etc.) is an optional bonus.
- **`GET /api/v1/profiles/{profile_uuid}/queries`** — All sub-queries from the most recent run, sorted
  by opportunity score (highest first). Supports:
  - `?min_score=0.5` (minimum opportunity score)
  - `?status=visible|not_visible|unknown`
  - `?page=1&per_page=20` (pagination)
  - Each query includes: `query_text`, `estimated_search_volume` (int), `competitive_difficulty` (0–100),
    `opportunity_score` (float 0–1, our formula), `domain_visible` (bool),
    `visibility_position` (int or null), `discovered_at` (ISO timestamp).
- **`GET /api/v1/profiles/{profile_uuid}/recommendations`** — Content recommendations. Each includes:
  `recommendation_uuid`, `target_query_uuid`, `content_type` (blog_post / landing_page / faq),
  `title`, `rationale`, `target_keywords` (list), `priority` (high / medium / low).
- **`POST /api/v1/queries/{query_uuid}/recheck`** — Re-run Retrieval + Extraction + Analysis for a
  **single** query and return updated data (useful after publishing content or after a fallback run).

---

## 11. Persistence

We must store and be able to retrieve: **profiles**, **runs**, **queries**, and **recommendations**.
(A local database such as SQLite is perfectly fine for the scope.)

---

## 12. What we must deliver

1. **Source code** — the DAG agent system (Python + LangChain/LangGraph) **plus** the API server and
   persistence layer.
2. **README.md** containing:
   - Architecture overview + DAG diagram
   - Setup / run instructions
   - Explanation of each agent's responsibility
   - How failures/retries work, **with an example of a simulated failure**
   - How observability works, **with a sample trace/log excerpt**
   - Known limitations + what we'd improve with more time
3. **Tests** covering at minimum:
   - one **happy-path** run,
   - one **simulated API failure** that successfully retries / falls back,
   - **tool-call argument validation**.
4. **`.env.example`** documenting required config (API keys, timeouts, retry limits, etc.).

---

## 13. How we will be graded (and how we win each area)

| Area                  | What they want                                                                    | How we score 10/10                                                         |
| --------------------- | --------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| **Agent design**      | One job per agent, clean interfaces                                               | 5 truly separate nodes, typed inputs/outputs between them                  |
| **DAG orchestration** | Non-linear graph, sensible conditionals                                           | Real LangGraph with named nodes, conditional edges, fallback branch        |
| **Tool calling**      | Typed schemas, arg validation, correct invocation                                 | Pydantic tool schemas, validate before calling, one tool per API call      |
| **API design**        | Sensible REST + status codes, correct shapes, sound persistence, input validation | Exact response shapes, proper codes (201/200/404/422), validated inputs    |
| **Resilience**        | Real retry/backoff, error classification, graceful degradation                    | Backoff+jitter, retryable vs non-retryable, fallback node, circuit breaker |
| **Observability**     | Logs/traces that help debug a real incident                                       | JSON logs per node, correlation-ID trace, metrics summary                  |
| **Code quality**      | Readability, typing, testing, structure                                           | Type hints, clean modules, pytest suite, clear layout                      |
| **Communication**     | Clear README + tradeoff explanations                                              | Thorough README, diagram, documented tradeoffs                             |

---

## 14. Ground rules & scope

- **Time expectation:** 5–7 hours. Stubbing/mocking parts is explicitly allowed — but we document what
  we'd do next for anything stubbed.
- **Authentication is out of scope.**
- **Synchronous execution is acceptable** for the run endpoint.
- Submit as a **Git repository** with a clear commit history, and a **single command** to run locally
  (e.g., `make run` or `python main.py`).

---

## 15. Important clarification: is there a frontend?

**The assessment does not require one** — it is backend-only (agent system + JSON API + persistence).
There is no frontend requirement anywhere in the document.

**However, by our own choice, we are building a responsive dashboard frontend to impress** — as a
deliberate extra that shows end-to-end product sense. It is clearly labeled "beyond assessment scope"
and is built **only after** the graded backend is 100% complete and bulletproof, so it never distracts
from the primary graded criteria. The backend alone must still earn 10/10 on its own; the frontend is
upside on top. (See `PLAN.md` Phase 11 for the frontend build details.)
