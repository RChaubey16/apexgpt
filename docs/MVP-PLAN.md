# ApexGPT — MVP Development Plan

ApexGPT is a Formula 1 RAG chat application that answers questions about drivers, constructors, circuits, seasons, races, crashes, rivalries and championship battles from **1950 to 2025**. Live/current-season data comes in a later phase.

Related docs:
- [FEATURES.md](./FEATURES.md): full feature plan by tier
- [DATA-STRATEGY.md](./DATA-STRATEGY.md): what data is stored and how it is kept lean
- [PROGRESS.md](./PROGRESS.md): development progress tracker (start here when resuming)

---

## 1. Key Decisions

| Area | Decision |
|---|---|
| Backend | Python, FastAPI |
| Frontend | Next.js (App Router, TypeScript, Tailwind) |
| Database (prod) | **Neon free tier**: serverless Postgres + pgvector (structured stats + vectors in one DB) |
| Database (local dev) | Postgres + pgvector container, same major version as Neon |
| Embeddings | `BAAI/bge-small-en-v1.5` via **fastembed** (ONNX Runtime, no PyTorch) |
| Reranker | `BAAI/bge-reranker-base` via **fastembed** |
| LLM | Free tiers only, via LiteLLM: Groq (primary) → Gemini → OpenRouter `:free` (fallbacks) |
| Data sources | Jolpica-F1 (structured, Ergast successor), Wikipedia (narrative, CC BY-SA, attributed in citations) |
| Containers | Docker from day one; Docker Compose for local dev |
| Hosting | Hostinger KVM2 (2 vCPU, 8 GB RAM, no GPU) via Coolify, **deployed as the final MVP phase** |
| Accounts | Not in MVP |
| Audience | Personal project for now, built to grow |

### Architecture: Hybrid RAG

F1 questions are either **narrative** ("What happened at Suzuka 1989?") or **statistical** ("Who has the most wins at Monza?"). Plain vector RAG gets counting and ranking questions wrong, so ApexGPT uses:

- **Structured tables**: every race, result, qualifying session, standing, driver, constructor and circuit (1950–2025).
- **Vector store**: narrative text such as race reports, season summaries, bios, rivalries and crashes.
- **LLM router (tool calling)**: chooses SQL, semantic search or both, then composes a grounded, cited answer.

### VPS Resource Budget

The database runs on Neon, so the VPS only hosts the app containers:

| Service | Approx. RAM |
|---|---|
| FastAPI + fastembed (embedder + reranker) | ~0.5–0.7 GB |
| Next.js (standalone) | ~300 MB |
| **ApexGPT total** | **~0.8–1 GB** |
| Coolify + Traefik (shared with other apps) | ~1 GB |

Implications:
- No local LLM inference on the VPS.
- Bulk corpus embedding runs on the dev machine. The VPS only embeds user queries.
- Local containers use memory limits matching this budget, so resource issues surface before deployment.

### Why Neon

- **1 GB storage per project** on the free tier, so the ~110–150 MB target leaves ~85% headroom.
- **Up to 100 free projects**, so future apps on the same account each get their own database.
- **Auto-suspend and auto-wake**: no manual restores and no keep-alive jobs.
- **Branching**: copy the database instantly to test a new ingestion run before promoting it.
- **Standard Postgres + pgvector** (`halfvec`, HNSW), so leaving is a `pg_dump`/restore.

### Neon Free-Tier Constraints

| Constraint | Mitigation |
|---|---|
| 1 GB storage per project (writes that add data fail beyond it; reads continue) | Lean data strategy (~110–150 MB target) plus an ingestion size guard (warns at 700 MB, refuses at 900 MB). See [DATA-STRATEGY.md](./DATA-STRATEGY.md). |
| Suspends after 5 min idle; ~0.5–1 s cold start on the next query | Frontend calls `/health/ready` on page load to wake the DB before the user sends a question; measure first-query latency in Phase 6. The Docker healthcheck uses DB-free `/health` so it never keeps Neon awake |
| 100 compute-hours/month per project | Compute only runs while awake, which is ample for a personal project; track usage in the Neon console |
| Network round trip from VPS to Neon (~20–80 ms) | Acceptable next to LLM latency; use Neon's pooled connection string; pick the region closest to the VPS |
| Free-tier backup/restore window is limited | Scheduled weekly `pg_dump` to off-site storage |
| Need for future growth | Upgrade the Neon plan, or dump/restore to self-hosted pgvector |

---

## 2. MVP Features

1. **Conversational Q&A**: natural-language chat, streaming responses, follow-up awareness, inline source citations, honest "I don't know".
2. **Accurate stats answers**: counting, ranking and comparison questions answered via SQL over structured data, rendered as tables where appropriate.
3. **Full coverage 1950–2025**: championships, races, qualifying, sprints, fastest laps, DNFs, points-system and regulation eras, constructor lineage.
4. **Basic chat UX**: starter questions, copy answer, browser-local chat history, answer feedback (👍/👎).

---

## 3. Repo Structure

```
apexgpt/
├── backend/                 # FastAPI app
│   ├── app/
│   │   ├── api/             # routes: /chat, /feedback, /health, /health/ready
│   │   ├── core/            # config, logging, rate limiting, in-memory cache
│   │   ├── db/              # SQLAlchemy models, session, Alembic migrations
│   │   ├── llm/             # LiteLLM client, prompts, provider fallback
│   │   ├── retrieval/       # hybrid search, reranker, entity resolution
│   │   └── tools/           # query_stats, search_f1_knowledge
│   ├── tests/
│   └── Dockerfile
├── ingestion/               # offline pipelines (run on dev machine)
│   ├── structured/          # Jolpica → Postgres
│   ├── narrative/           # Wikipedia → clean → chunk → embed → pgvector
│   │   └── topics.yaml      # curated topic article list
│   ├── size_guard.py        # DB size budget checks
│   └── Dockerfile
├── frontend/                # Next.js app
│   └── Dockerfile
├── eval/                    # golden Q&A set + eval runner
├── data/                    # raw downloads (git-ignored)
├── docs/
├── docker-compose.yml       # local dev (db, backend, frontend)
├── docker-compose.prod.yml  # Coolify deployment (backend, frontend; DB = Neon)
└── .env.example
```

---

## 4. Phases

### Phase 0: Local Foundation (2–3 days)

- Monorepo setup: git, `.editorconfig`, pre-commit (ruff, black, eslint, prettier).
- Docker Compose services: `db` (Postgres + pgvector ≥ 0.7 for `halfvec`, same major version as Neon), `backend`, `frontend`.
- FastAPI app with `/health`, config via `pydantic-settings` (single `DATABASE_URL` that switches between local and Neon).
- Alembic initialised. The first migration enables the `vector` extension.
- Next.js shell with a placeholder chat page calling `/health/ready`.
- Multi-stage, production-ready Dockerfiles from the start.
- Container memory limits matching the VPS budget.
- GitHub Actions running lint and tests.

**Done when:** `docker compose up` brings up all services locally and the frontend shows a healthy backend.

### Phase 1: Structured F1 Data (1 week)

- Schema (compact types, no redundant columns): `seasons`, `circuits`, `drivers`, `constructors`, `races`, `results`, `sprint_results`, `qualifying`, `driver_standings`, `constructor_standings`, `pit_stops`, `status`.
- **`lap_times` is deferred** to the Live Season phase (see [DATA-STRATEGY.md](./DATA-STRATEGY.md)).
- Loader: Jolpica bulk dump if available, otherwise a polite, rate-limited API crawl with local caching into `data/`.
- **Alias tables** for entity resolution ("Schumi" → Michael Schumacher, "Checo" → Sergio Pérez).
- **Constructor lineage table** (Tyrrell → BAR → Honda → Brawn → Mercedes, etc.).
- LLM-friendly SQL views: `v_driver_career`, `v_race_winners`, `v_season_summary`, `v_head_to_head_teammates`.
- Read-only Postgres role with a statement timeout for the LLM's SQL tool.

**Done when:** sanity checks pass (e.g. Hamilton = 105 wins, 2021 champion = Verstappen, 1950 = 7 championship races) and structured data is under ~25 MB.

### Phase 2: Narrative Corpus (1–1.5 weeks)

Follows the rules in [DATA-STRATEGY.md](./DATA-STRATEGY.md).

- Collect via the MediaWiki API, by importance:
  - 76 season articles (full)
  - ~1,150 Grand Prix race reports (background + race report sections)
  - ~250 notable drivers (full) and ~530 other drivers (intro only)
  - ~60 major constructors (full) and ~100 minor (intro only)
  - ~77 circuits (intro + history)
  - ~150 curated topic articles from `topics.yaml`
- Notable drivers and major constructors are computed from the Phase 1 data.
- Strip all tables, boilerplate sections, infoboxes, navboxes and citation markers.
- Chunk by section (~400–600 tokens, ~50-token overlap within sections) with integer metadata: `season`, `race_id`, `driver_ids[]`, `constructor_ids[]`, `circuit_id`, `topic`, `section`, `source_url`.
- Embed on the dev machine with fastembed (`bge-small-en-v1.5`). Store in a `chunks` table with a `halfvec(384)` column and HNSW index, plus a GIN index on `to_tsvector(text)` (no stored `tsvector`).
- Raw articles stay in `data/`; only chunks go into the DB.
- Size guard runs after every load.

**Done when:** searching "Senna Prost Suzuka collision" returns the 1989/1990 Japanese GP chunks, and the corpus is ~12–15k chunks under ~120 MB.

### Phase 3: Retrieval & LLM Layer (1.5 weeks)

- **Hybrid search:** vector and full-text results merged via Reciprocal Rank Fusion. Metadata filters are extracted from the query (e.g. "1986" → season filter). The top results are reranked with `bge-reranker-base` (fastembed) to keep the best 5.
- **LLM client:** LiteLLM with Groq as primary (Llama 3.3 70B or similar), and automatic fallback to Gemini, then OpenRouter, on 429s or errors.
- **Tools (function calling):**
  - `query_stats(sql)`: text-to-SQL over the helper views, using the read-only role, with validation and row limits.
  - `search_f1_knowledge(query, filters)`: hybrid search.
- **Entity resolution** maps names and aliases to IDs before tools run.
- **Grounded answer prompt:** cite sources, use tables for stats, admit gaps, treat 2026+ as out of scope.

**Done when** these answer correctly from the CLI:
- "Who has the most wins at Monza?" (stats)
- "Explain Abu Dhabi 2021" (narrative)
- "How did Hunt beat Lauda in 1976 and what were the final points?" (both)

### Phase 4: Chat API (4–5 days)

- `POST /api/chat` streams over **SSE** with typed events: `token`, `citation`, `table`, `done`, `error`.
- Conversation memory: the client sends recent history, and the backend condenses follow-ups into standalone questions.
- `POST /api/feedback` stores thumbs up/down (question, answer excerpt ≤500 chars, rating), kept for 90 days.
- Rate limiting per IP (`slowapi`), plus an **in-memory** LRU cache for repeated questions.
- Structured logging to rotated **files** (not the DB): question, tools used, latency, provider, errors.
- Unit tests for the tools and an integration test for `/chat`.

### Phase 5: Frontend MVP (1 week)

- Chat UI with streaming text and markdown rendering, including stats tables.
- Citation chips (Wikipedia links, race references).
- Starter question cards on an empty chat.
- Conversation history in `localStorage` (new, rename, delete).
- Copy answer and 👍/👎 feedback.
- Responsive, F1-themed dark UI.
- Can start early against a mocked `/chat` once the Phase 4 API contract is defined.

### Phase 6: Evaluation & Hardening (4–5 days)

- Golden set of ~100 questions across categories: stats, seasons, races, crashes, rivalries, multi-hop, trick and out-of-scope.
- Eval runner: exact-match scoring for stats, LLM-as-judge for narrative grounding.
- Tune chunk size, reranker cutoff, prompts and SQL-view coverage. Check whether any intro-only entities need fuller coverage.
- Load test under the VPS memory caps and free-tier LLM rate limits.

### Phase 7: Deployment (2–3 days) 🏁

- **Neon:** create the project in the region closest to the VPS, enable `vector`, run Alembic migrations, create the read-only role.
- Load data into Neon: `pg_dump` from local, restore to Neon, then run the size guard against Neon.
- Optional: use a Neon branch for future ingestion runs (load → run eval → promote or discard).
- `docker-compose.prod.yml` (backend + frontend) deployed via Coolify, connected to Neon through the pooled connection string.
- Domain, SSL, env vars and secrets configured in Coolify.
- GitHub Actions workflow: scheduled weekly `pg_dump` backup.
- Health checks and restart policies.
- Smoke test the golden set against production.

**Done when:** ApexGPT is live on its domain and passes the production smoke test.

---

## 5. Development Workflow

### Branching

- `main`: the only long-lived branch. There is no `develop` branch.
- `feature/<name>`: one branch per feature from the breakdown below, created from the latest `main`.
- Each feature's commit uses the **commit message given in the breakdown** (Conventional Commits).
- When a feature passes the completion checklist, a **PR is raised against `main`**.
- The user **reviews and merges every PR**. Work on the next feature starts only after the merge.
- Commits and PRs never include Claude/Claude Code co-author attribution.

**Feature cycle:** pull latest `main` → create `feature/<name>` → build → completion checklist → commit → push → PR to `main` → user reviews and merges → next feature.

### Feature Completion Checklist

A feature is committed and merged only when **every** item is true:

- [ ] **Implementation:** everything in the feature's scope is built; nothing is stubbed or left as a TODO.
- [ ] **Validation:** inputs are validated at boundaries (API request models, config/env vars, external data from Jolpica/Wikipedia/LLM responses).
- [ ] **Error handling:** expected failures are handled (network errors, rate limits, timeouts, bad data, empty results) with clear messages; no secrets or stack traces leak to users.
- [ ] **Tests:** unit tests for new logic, plus integration tests where the feature crosses a boundary (DB, HTTP, LLM). External services are mocked in unit tests.
- [ ] **Lint and format pass:** ruff + black (Python), eslint + prettier (TypeScript).
- [ ] **All tests pass:** the full backend/ingestion/frontend suites, not just the new tests.
- [ ] **Docker builds:** images for affected services build and start with `docker compose up`.
- [ ] **Docs updated:** `.env.example`, README and these docs reflect any new config or behaviour.
- [ ] **`PROGRESS.md` updated:** feature marked "PR raised" (ticked after merge), status, next steps and session log updated.
- [ ] **PR raised** against `main` with a summary of the scope, how it was tested and anything to review closely.

---

## 6. Feature Breakdown

Each feature has an ID, a branch name and the commit message to use. Features run in the order listed.

### Phase 0: Local Foundation

| ID | Branch | Scope | Commit message |
|---|---|---|---|
| F0.1 | `feature/repo-setup` | `.gitignore` (incl. `data/`), `.editorconfig`, shared `ruff.toml`, pre-commit (file hygiene, ruff, black), `.env.example`, README | `chore: initialize monorepo with tooling and pre-commit hooks` |
| F0.2 | `feature/backend-skeleton` | FastAPI app, `/health`, `pydantic-settings`, pytest setup, multi-stage Dockerfile | `feat: add FastAPI backend skeleton with health endpoint` |
| F0.3 | `feature/database-setup` | Postgres + pgvector service, SQLAlchemy session, Alembic init, migration enabling `vector`, DB readiness check at `/health/ready` (`/health` stays DB-free liveness) | `feat: add pgvector database with Alembic migrations` |
| F0.4 | `feature/frontend-skeleton` | Next.js (App Router, TS, Tailwind) shell calling `/health/ready`, Vitest + Testing Library, multi-stage Dockerfile (`NEXT_PUBLIC_API_URL` build arg), eslint + prettier pre-commit hooks | `feat: add Next.js frontend shell with backend health check` |
| F0.5 | `feature/docker-compose-setup` | Full `docker-compose.yml` (db, backend, frontend), memory limits, healthchecks | `chore: add docker compose stack with memory limits` |
| F0.6 | `feature/ci-pipeline` | GitHub Actions: lint + tests + Docker build | `chore: add CI workflow for lint, tests and docker builds` |

### Phase 1: Structured F1 Data

| ID | Branch | Scope | Commit message |
|---|---|---|---|
| F1.1 | `feature/f1-schema` | Tables for seasons, circuits, drivers, constructors, races, results, sprint results, qualifying, standings, pit stops, status (compact types) | `feat: add structured F1 data schema` |
| F1.2 | `feature/jolpica-loader` | Bulk dump or rate-limited crawl, cache in `data/`, idempotent load for 1950–2025 | `feat: add Jolpica loader for 1950-2025 F1 data` |
| F1.3 | `feature/entity-aliases` | Driver/constructor alias tables, constructor lineage table, seed data | `feat: add entity alias and constructor lineage tables` |
| F1.4 | `feature/stats-views` | `v_driver_career`, `v_race_winners`, `v_season_summary`, `v_head_to_head_teammates` | `feat: add LLM-friendly stats SQL views` |
| F1.5 | `feature/readonly-db-role` | Read-only role limited to views, statement timeout | `security: add read-only database role for LLM queries` |
| F1.6 | `feature/structured-data-checks` | Sanity tests (Hamilton 105 wins, 2021 champion, 1950 race count), size check < ~25 MB | `test: add sanity checks for structured F1 data` |

### Phase 2: Narrative Corpus

| ID | Branch | Scope | Commit message |
|---|---|---|---|
| F2.1 | `feature/wiki-fetcher` | MediaWiki API client, polite rate limiting, local cache in `data/` | `feat: add MediaWiki article fetcher with local cache` |
| F2.2 | `feature/article-selection` | Notable driver / major constructor rules from Phase 1 data, season/race/circuit lists, `topics.yaml` | `feat: add article selection rules and curated topics list` |
| F2.3 | `feature/article-cleaner` | Strip tables, boilerplate sections, infoboxes, navboxes, citation markers | `feat: add Wikipedia article cleaner` |
| F2.4 | `feature/chunker` | Section-based chunking (~400–600 tokens), metadata linked to Phase 1 IDs | `feat: add section-based chunker with entity metadata` |
| F2.5 | `feature/embedding-pipeline` | `chunks` table (`halfvec(384)`, HNSW, GIN on `to_tsvector`), fastembed embedding + upsert | `feat: add fastembed embedding pipeline and chunks table` |
| F2.6 | `feature/size-guard` | Per-table size report, warn 700 MB, refuse 900 MB | `feat: add database size guard to ingestion` |

### Phase 3: Retrieval & LLM Layer

| ID | Branch | Scope | Commit message |
|---|---|---|---|
| F3.1 | `feature/hybrid-search` | Vector + full-text search, Reciprocal Rank Fusion, metadata filters | `feat: add hybrid vector and full-text search` |
| F3.2 | `feature/reranker` | `bge-reranker-base` via fastembed, top-5 selection | `feat: add reranker to retrieval pipeline` |
| F3.3 | `feature/llm-client` | LiteLLM wrapper, Groq → Gemini → OpenRouter fallback, timeouts, retries | `feat: add LLM client with free-provider fallback` |
| F3.4 | `feature/entity-resolution` | Map names/aliases to driver, constructor and circuit IDs | `feat: add entity resolution for F1 names and aliases` |
| F3.5 | `feature/stats-tool` | `query_stats` text-to-SQL tool: SQL validation (SELECT-only, views-only), row limits | `feat: add text-to-SQL stats tool` |
| F3.6 | `feature/knowledge-search-tool` | `search_f1_knowledge` tool wrapping hybrid search + reranker | `feat: add F1 knowledge search tool` |
| F3.7 | `feature/answer-orchestrator` | Tool-calling router, grounded answer prompt, citations, CLI for the 3 test questions | `feat: add tool-calling answer orchestrator` |

### Phase 4: Chat API

| ID | Branch | Scope | Commit message |
|---|---|---|---|
| F4.1 | `feature/chat-endpoint` | `POST /api/chat`, SSE events (`token`, `citation`, `table`, `done`, `error`) | `feat: add streaming chat endpoint` |
| F4.2 | `feature/conversation-memory` | Follow-up condensing from client-sent history | `feat: add follow-up question handling` |
| F4.3 | `feature/feedback-endpoint` | `POST /api/feedback`, feedback table, 90-day retention job | `feat: add answer feedback endpoint` |
| F4.4 | `feature/rate-limiting-cache` | `slowapi` per-IP limits, in-memory LRU response cache | `feat: add rate limiting and response cache` |
| F4.5 | `feature/structured-logging` | JSON logs to rotated files (question, tools, latency, provider, errors) | `feat: add structured file logging` |

### Phase 5: Frontend MVP

| ID | Branch | Scope | Commit message |
|---|---|---|---|
| F5.1 | `feature/chat-ui` | Chat layout, SSE streaming client, `/health/ready` on page load (wakes Neon) | `feat: add streaming chat interface` |
| F5.2 | `feature/answer-rendering` | Markdown, stats tables, citation chips | `feat: add markdown, table and citation rendering` |
| F5.3 | `feature/starter-questions` | Starter question cards on empty chat | `feat: add starter question cards` |
| F5.4 | `feature/chat-history` | `localStorage` conversations (new, rename, delete) | `feat: add local conversation history` |
| F5.5 | `feature/answer-actions` | Copy answer, 👍/👎 feedback | `feat: add copy and feedback actions` |
| F5.6 | `feature/ui-theme` | Responsive F1-themed dark UI polish | `feat: add responsive F1 dark theme` |

### Phase 6: Evaluation & Hardening

| ID | Branch | Scope | Commit message |
|---|---|---|---|
| F6.1 | `feature/golden-eval-set` | ~100 questions with expected answers across all categories | `test: add golden evaluation question set` |
| F6.2 | `feature/eval-runner` | Exact-match scoring for stats, LLM-as-judge for narrative, report output | `test: add evaluation runner` |
| F6.3 | `feature/retrieval-tuning` | Tune chunking, reranker cutoff, prompts and SQL views from eval results | `refactor: tune retrieval and prompts from eval results` |
| F6.4 | `feature/load-testing` | Load tests under memory caps, cold-start latency measurement | `test: add load and cold-start latency tests` |

### Phase 7: Deployment

| ID | Branch | Scope | Commit message |
|---|---|---|---|
| F7.1 | `feature/prod-compose` | `docker-compose.prod.yml` for Coolify (backend, frontend), healthchecks, restart policies | `chore: add production docker compose for Coolify` |
| F7.2 | `feature/neon-setup` | Scripts for Neon migrations, read-only role and data restore; size guard against Neon | `chore: add Neon setup and data restore scripts` |
| F7.3 | `feature/backup-workflow` | Weekly `pg_dump` GitHub Actions workflow | `chore: add weekly database backup workflow` |
| F7.4 | `feature/prod-smoke-test` | Golden-set smoke test against production URL | `test: add production smoke test` |

After F7.4 is merged: deploy `main` via Coolify, run the smoke test and tag `v1.0.0`.

---

## 7. Timeline

| Phase | Estimate | Cumulative |
|---|---|---|
| 0. Local foundation | 2–3 days | ~0.5 wk |
| 1. Structured data | 1 wk | ~1.5 wk |
| 2. Narrative corpus | 1–1.5 wk | ~3 wk |
| 3. Retrieval + LLM | 1.5 wk | ~4.5 wk |
| 4. Chat API | 4–5 days | ~5.5 wk |
| 5. Frontend MVP | 1 wk | ~6.5 wk |
| 6. Eval + hardening | 4–5 days | ~7 wk |
| 7. Deployment | 2–3 days | **~7.5–8 wk** |

Estimates assume part-time solo work. Phases 1 and 2 can run in parallel; Phase 5 can start against a mocked API.

---

## 8. Post-MVP Roadmap (to be prioritised later)

Summary below; full details in [FEATURES.md](./FEATURES.md).

**Tier 2: Enhanced experience**
- Entity pages: driver, constructor, circuit and season profiles; clickable entity links in answers.
- Comparisons: driver vs driver, teammate head-to-heads, era comparisons.
- Visual answers: points-progression charts, win/podium charts, career timelines.
- Curated collections: rivalries, title deciders, safety & crashes, iconic races.

**Tier 3: Engagement & power features**
- Trivia/quiz mode generated from structured data.
- "On This Day" in F1 history.
- Beginner "explain the sport" mode.
- Era/season/driver scope filters for chat.
- User accounts: saved chats, favourites, bookmarks.

**Live Season phase**
- Post-race-weekend ingestion job for results, standings and reports.
- Current-season context in answers.
- `lap_times` returns, with FastF1 telemetry analysis (2018+): lap comparisons, tyre strategy.
- Auto-generated race weekend summaries.

**Ops (ongoing)**
- Re-runnable ingestion pipeline triggered via CLI or admin endpoint.
- Growing evaluation set to catch retrieval regressions.
- Query, latency and token-usage monitoring.
- Database size and compute-hour monitoring against the Neon free-tier limits.
