# ApexGPT — Development Progress

Tracks where development stands, so work can resume after any interruption.

**How to resume:** read **Current Status** and **Next Steps**, check the open phase's feature checklist, then review the latest **Session Log** entry.

**How to update:** when a feature passes the Feature Completion Checklist ([MVP-PLAN.md §5](./MVP-PLAN.md#5-development-workflow)) and its PR to `main` is raised, mark it `🔍 PR #<n>`. Tick it only after the user merges the PR. Update Current Status and Next Steps, and add a Session Log entry at the end of each work session. Record any change to an agreed decision in the Decision Log.

Related docs: [MVP-PLAN.md](./MVP-PLAN.md) · [FEATURES.md](./FEATURES.md) · [DATA-STRATEGY.md](./DATA-STRATEGY.md)

---

## Current Status

| | |
|---|---|
| **Current phase** | Phase 0 done; Phase 1 (Structured data) not started |
| **Current feature** | None (next: F1.1 `feature/f1-schema`) |
| **Current branch** | `main` |
| **Open PR** | None |
| **Repo** | https://github.com/RChaubey16/apexgpt |
| **Last updated** | 2026-11-12 |
| **Blockers** | None |

## Next Steps

1. Optional (user): in GitHub branch protection for `main`, require the **CI passed** check.
2. When the user says to start Phase 1: pull `main`, start **F1.1** `feature/f1-schema`. Early in Phase 1, check whether Jolpica offers a bulk dump (needed for F1.2).

---

## Phase Overview

| Phase | Status | Started | Completed |
|---|---|---|---|
| Planning | ✅ Done | 2026-11-12 | 2026-11-12 |
| 0. Local foundation | ✅ Done | 2026-11-12 | 2026-11-12 |
| 1. Structured data | ⬜ Not started | | |
| 2. Narrative corpus | ⬜ Not started | | |
| 3. Retrieval + LLM | ⬜ Not started | | |
| 4. Chat API | ⬜ Not started | | |
| 5. Frontend MVP | ⬜ Not started | | |
| 6. Eval + hardening | ⬜ Not started | | |
| 7. Deployment | ⬜ Not started | | |

Status key: ⬜ Not started · 🟡 In progress · ✅ Done · ⛔ Blocked

---

## Feature Checklists

Branch names, scopes and commit messages for each feature are in [MVP-PLAN.md §6](./MVP-PLAN.md#6-feature-breakdown).

### Planning ✅
- [x] Feature list drafted ([FEATURES.md](./FEATURES.md))
- [x] MVP phase plan written ([MVP-PLAN.md](./MVP-PLAN.md))
- [x] Lean data strategy defined ([DATA-STRATEGY.md](./DATA-STRATEGY.md))
- [x] Database finalised (Neon free tier)
- [x] Progress tracker created
- [x] `CLAUDE.md` rules added
- [x] Development workflow, completion checklist and feature breakdown added

### Phase 0: Local Foundation ✅
- [x] F0.1 `feature/repo-setup`: monorepo tooling and pre-commit hooks · PR #1 merged
- [x] F0.2 `feature/backend-skeleton`: FastAPI skeleton with `/health` · PR #2 merged
- [x] F0.3 `feature/database-setup`: pgvector database with Alembic · PR #3 merged
- [x] F0.4 `feature/frontend-skeleton`: Next.js shell with health check · PR #4 merged
- [x] F0.5 `feature/docker-compose-setup`: full compose stack with memory limits · PR #5 merged
- [x] F0.6 `feature/ci-pipeline`: CI for lint, tests and Docker builds · PR #6 merged
- [x] **Phase done check:** `docker compose up` works and the frontend shows a healthy backend (verified in F0.5)

### Phase 1: Structured F1 Data
- [ ] F1.1 `feature/f1-schema`: structured F1 schema
- [ ] F1.2 `feature/jolpica-loader`: Jolpica loader 1950–2025
- [ ] F1.3 `feature/entity-aliases`: alias and lineage tables
- [ ] F1.4 `feature/stats-views`: stats SQL views
- [ ] F1.5 `feature/readonly-db-role`: read-only role for LLM queries
- [ ] F1.6 `feature/structured-data-checks`: sanity checks
- [ ] **Phase done check:** sanity checks pass; structured data < ~25 MB

### Phase 2: Narrative Corpus
- [ ] F2.1 `feature/wiki-fetcher`: MediaWiki fetcher with cache
- [ ] F2.2 `feature/article-selection`: selection rules + `topics.yaml`
- [ ] F2.3 `feature/article-cleaner`: Wikipedia cleaner
- [ ] F2.4 `feature/chunker`: section-based chunker with metadata
- [ ] F2.5 `feature/embedding-pipeline`: fastembed pipeline + `chunks` table
- [ ] F2.6 `feature/size-guard`: DB size guard
- [ ] **Phase done check:** "Senna Prost Suzuka collision" returns the 1989/1990 Japanese GP chunks; ~12–15k chunks, < ~120 MB

### Phase 3: Retrieval & LLM Layer
- [ ] F3.1 `feature/hybrid-search`: hybrid search with RRF
- [ ] F3.2 `feature/reranker`: reranker
- [ ] F3.3 `feature/llm-client`: LLM client with fallback
- [ ] F3.4 `feature/entity-resolution`: entity resolution
- [ ] F3.5 `feature/stats-tool`: text-to-SQL stats tool
- [ ] F3.6 `feature/knowledge-search-tool`: knowledge search tool
- [ ] F3.7 `feature/answer-orchestrator`: tool-calling orchestrator
- [ ] **Phase done check:** the three CLI test questions are answered correctly

### Phase 4: Chat API
- [ ] F4.1 `feature/chat-endpoint`: streaming chat endpoint
- [ ] F4.2 `feature/conversation-memory`: follow-up handling
- [ ] F4.3 `feature/feedback-endpoint`: feedback endpoint
- [ ] F4.4 `feature/rate-limiting-cache`: rate limiting + cache
- [ ] F4.5 `feature/structured-logging`: structured file logging

### Phase 5: Frontend MVP
- [ ] F5.1 `feature/chat-ui`: streaming chat interface
- [ ] F5.2 `feature/answer-rendering`: markdown, tables, citations
- [ ] F5.3 `feature/starter-questions`: starter question cards
- [ ] F5.4 `feature/chat-history`: local conversation history
- [ ] F5.5 `feature/answer-actions`: copy + feedback actions
- [ ] F5.6 `feature/ui-theme`: responsive F1 dark theme

### Phase 6: Evaluation & Hardening
- [ ] F6.1 `feature/golden-eval-set`: golden question set
- [ ] F6.2 `feature/eval-runner`: evaluation runner
- [ ] F6.3 `feature/retrieval-tuning`: tuning from eval results
- [ ] F6.4 `feature/load-testing`: load + cold-start tests

### Phase 7: Deployment 🏁
- [ ] F7.1 `feature/prod-compose`: production compose for Coolify
- [ ] F7.2 `feature/neon-setup`: Neon setup + data restore scripts
- [ ] F7.3 `feature/backup-workflow`: weekly backup workflow
- [ ] F7.4 `feature/prod-smoke-test`: production smoke test
- [ ] `main` deployed via Coolify, smoke test passed, tagged `v1.0.0`

---

## Decision Log

| Date | Decision | Reason |
|---|---|---|
| 2026-11-12 | Hybrid RAG: SQL for stats + pgvector for narrative | Vector-only RAG gets counting and ranking questions wrong |
| 2026-11-12 | Free LLMs only via LiteLLM (Groq → Gemini → OpenRouter) | No paid AI services |
| 2026-11-12 | No user accounts in MVP | Keep MVP scope small |
| 2026-11-12 | Deployment moved to the last MVP phase | User preference; production-ready Dockerfiles still built from Phase 0 |
| 2026-11-12 | fastembed (ONNX) instead of PyTorch for embeddings and reranking | Cuts backend RAM from ~1.5 GB to ~0.5 GB |
| 2026-11-12 | Lean data strategy; `lap_times` deferred | Keep DB ~110–150 MB; better retrieval quality |
| 2026-11-12 | Notable driver = champion, race winner, podium finisher, or 30+ starts | Full bios only where users are likely to ask |
| 2026-11-12 | Database: Neon free tier (after considering self-hosted and Supabase) | Saves VPS RAM; 1 GB/project; 100 free projects for future apps; auto-wake with no keep-alive |
| 2026-11-12 | Git flow: `main` + `feature/*` only (no `develop`), one feature at a time, PR per feature against `main`, user reviews and merges before the next feature starts; Conventional Commits; no Claude co-author | Rules in `CLAUDE.md` |
| 2026-11-12 | Local DB pinned to Postgres 18 + pgvector 0.8.1 | Matches Neon's default for new projects (PG 18, pgvector 0.8.1) |
| 2026-11-12 | Split health: `/health` (liveness, no DB) vs `/health/ready` (DB check) | A 30s Docker healthcheck hitting the DB would keep Neon awake 24/7 (~180 CU-h/month vs 100 free) |
| 2026-11-12 | Sync SQLAlchemy 2.1 + psycopg 3; prepared statements disabled | Simple with Alembic; low query volume; safe behind Neon's PgBouncer pooler |
| 2026-11-12 | Frontend: Next.js 16.4 (App Router, TS, Tailwind 4), standalone output; browser calls backend directly | `NEXT_PUBLIC_API_URL` is inlined at build time, so it's a Docker build arg; backend CORS allows the frontend origin |
| 2026-11-12 | Frontend tests: Vitest + Testing Library | Fast, works with React 19 and the `@/` alias |
| 2026-11-12 | CI: one GitHub Actions workflow, parallel jobs, single `CI passed` gate; actions pinned to commit SHAs; CI Postgres uses trust auth (no password literal) | One required check for branch protection; supply-chain safety; avoids secret-scanner false positives like the F0.3 GitGuardian alert |

---

## Session Log

Newest first.

### 2026-11-12: Phase 0 closed
- PR #6 (F0.6) merged. All Phase 0 features (F0.1–F0.6) merged and the phase done check passed, so **Phase 0 is complete**.
- Phase 0 delivers: monorepo tooling + pre-commit, FastAPI backend (liveness/readiness health), Postgres 18 + pgvector with Alembic, Next.js frontend shell, a compose stack with memory limits, and GitHub Actions CI (lint, tests, Docker builds, single `CI passed` gate).
- Phase 1 not started yet; waiting for the user's go-ahead.

### 2026-11-12: F0.6 CI pipeline
- PR #5 (F0.5) merged.
- Added `.github/workflows/ci.yml` (PRs to `main`, pushes to `main`, manual dispatch; `contents: read`; superseded PR runs are cancelled). Jobs:
  - **Lint:** `pre-commit run --all-files` (pinned pre-commit 4.7.0 via `uvx`, hook envs cached, frontend `npm ci` first for prettier/eslint).
  - **Backend:** uv 0.11.2 (same as the Dockerfile), `pytest` with a `pgvector/pgvector:0.8.1-pg18` service so integration tests run; a guard step fails if they're collected as skipped.
  - **Frontend:** `typecheck` + Vitest.
  - **Docker runtime images:** buildx with GHA cache; backend + frontend production images started and must reach `healthy`; checked non-root. Backend started with an unreachable DB to prove liveness doesn't depend on the DB.
  - **Compose:** `docker compose up --build --wait` from `.env.example`; curls `/health`, `/health/ready`, frontend `/api/health` and `/`, and the CORS header; logs dumped on failure; `down -v` always.
  - **CI passed:** aggregate gate over all jobs.
- Added actionlint to pre-commit (runs shellcheck on `run:` blocks in CI, where shellcheck is preinstalled).
- README: CI section.
- Verified locally: `pre-commit run --all-files` passes (incl. actionlint); integration-guard regex matches `5/38 tests collected` and rejects `no tests collected`. Full verification is the PR's own CI run.
- PR #6 raised. First CI run all green (~3 min wall-clock): 38 backend tests passed with the integration guard showing `5/38 tests collected`; 30 Vitest tests; runtime images healthy and running as `app` (backend 214 MB, frontend 235 MB); compose stack returned `/health/ready` `{"database":"ok"}` and the correct CORS header; GitGuardian passed.

### 2026-11-12: F0.5 docker compose stack
- PR #4 (F0.4) merged.
- `docker-compose.yml` now runs db + backend + frontend (dev targets, hot reload via source bind mounts; deps stay in images).
- Backend container runs `alembic upgrade head` then `uvicorn --reload`; uses new `COMPOSE_DATABASE_URL` (host `db`), so no credentials-bearing URL is written in the compose file. Compose fails with a clear message if it's missing.
- Startup order via healthchecks: db (pg_isready) → backend (`/health`) → frontend (`/api/health`). All ports bound to `127.0.0.1`.
- Limits mirror the VPS budget: backend 768M / 1 CPU, frontend (next dev) 1G / 1 CPU, db 512M / 1 CPU (local only). Production limits come in F7.1.
- Verified: all 3 healthy; idle RAM db ~28 MB, backend ~86 MB, frontend (dev) ~231 MB; `/health/ready` ok; CORS ok; 33 backend tests pass inside the container; backend and frontend hot reload confirmed; fresh stack from an empty volume (separate project name and ports) migrates and comes up healthy, then removed with `down -v`; Chrome shows "All systems go".
- Noted: Next dev overlay shows a hydration warning caused by the ClickUp Chrome extension adding a class to `<body>`, not by app code.
- PR raised against `main`; awaiting review.

### 2026-11-12: F0.4 frontend skeleton
- PR #3 (F0.3) merged. User cleared Docker networks; `docker compose up` verified.
- Scaffolded Next.js 16.4.6 (`create-next-app`, App Router, TS, Tailwind 4, src dir); read bundled Next 16 docs (standalone output, build-time `NEXT_PUBLIC_*`, route handlers) as the scaffold's `AGENTS.md` instructs.
- Home page shell with `BackendStatus`: calls `/health/ready` on load (wakes Neon), 10s timeout, states ready / database unavailable / unreachable / unexpected response / misconfigured, Retry button, `aria-live`.
- `NEXT_PUBLIC_API_URL` validated (http/https, no credentials/query/fragment). `/api/health` = frontend liveness. `poweredByHeader` off.
- Multi-stage Dockerfile: `deps` → `dev` (next dev) → `builder` (requires `NEXT_PUBLIC_API_URL` build arg) → `runtime` (standalone, non-root, HEALTHCHECK).
- Pre-commit: Prettier + ESLint hooks running the frontend's pinned versions; ESLint config extends `eslint-config-prettier`.
- Fixes along the way: `@types/node` ^20 → ^22 (matches Node 22 runtime; Vitest peer); explicit Testing Library cleanup; `typecheck` runs `next typegen` first; refactored effect to satisfy React Compiler's `set-state-in-effect` rule instead of disabling it; added `public/robots.txt` so `public/` exists in clean clones.
- Verified: 30 Vitest tests; lint (0 warnings); typecheck; Prettier; Docker build fails without the build arg; runtime image 231 MB, ~35 MB RAM, healthy, non-root; in Chrome against local backend + compose DB: "All systems go" → DB stopped → "database unavailable" + Retry → DB restarted → Retry → "All systems go"; backend stopped → "Can't reach the backend"; no console errors.
- `npm audit`: 8 moderate advisories from one root cause, `minimatch` 10.2.6 DoS (GHSA-g3hv-75wg-m249) via `@typescript-eslint/typescript-estree` (lint-time only). `npm audit fix --force` would be breaking, so added a scoped npm `overrides` entry → `minimatch@^11.0.1` for that package only. Now 0 vulnerabilities; ESLint verified working. Remove the override once `typescript-eslint` ships the fix.
- PR raised against `main`; awaiting review.

### 2026-11-12: F0.3 database setup
- PR #2 (F0.2) merged.
- Confirmed Neon's default: Postgres 18 + pgvector 0.8.1. Local `db` service pinned to `pgvector/pgvector:0.8.1-pg18`, bound to `127.0.0.1` only, `pg_isready` healthcheck, volume at `/var/lib/postgresql` (PG 18 layout).
- Backend: SQLAlchemy 2.1 (sync) + psycopg 3 + Alembic. Engine on `app.state` (lazy connect, `pool_pre_ping`, small pool, prepared statements off for PgBouncer). `DATABASE_URL` required, validated, normalised to `postgresql+psycopg`, held as `SecretStr`. `hide_input_in_errors` stops secrets appearing in validation errors (a test caught the leak).
- Health split: `/health` liveness (never touches DB) vs `/health/ready` (DB check, 503 when down). App now built via `uvicorn --factory`.
- Alembic: `alembic.ini`, `migrations/env.py` (URL from Settings), migration `0001` enables `vector`. Migrations ship in the runtime image.
- Tests: 38 passing (33 unit + 5 integration against real PG 18: pgvector ≥ 0.7 + `halfvec` distance, idempotent upgrade, downgrade, server version 18, `/health/ready`).
- Verified in Docker: in-image `alembic upgrade head`; `/health/ready` 200 → 503 when DB stopped, `/health` stays 200 and container stays healthy; logs show only the error class; ~70 MB RAM.
- **Local env issue (resolved):** `docker compose up` first failed ("all predefined address pools have been fully subnetted") due to unused Docker networks from other projects; the user cleared some. Port 5432 is used by another local Postgres, so the local `.env` uses `POSTGRES_PORT=55432`.
- Verified via `docker compose up -d db`: healthy, bound to `127.0.0.1:55432`; `alembic upgrade head` using `.env`; all 38 tests pass; local backend `/health/ready` returns 200; data (pgvector 0.8.1, revision `0001`) persists across `docker compose down`/`up` in volume `apexgpt_pgdata`.
- PR raised against `main`.
- **GitGuardian check failed** ("Generic Password" in `docker-compose.yml`): a false positive on `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?...}`, an interpolation placeholder with no real value. Restructured the `db` env to pass-through names (`- POSTGRES_PASSWORD`), so no `KEY: value` password line exists. Verified: `docker compose config` resolves values from `.env`; without them the image refuses to initialise. Only the three `POSTGRES_*` vars reach the DB container (not the whole `.env`). The GitGuardian dashboard incident needs to be marked as a false positive.

### 2026-11-12: F0.2 backend skeleton
- PR #1 (F0.1) merged.
- Added `backend/`: uv project (Python 3.12, lockfile), FastAPI app factory, `/health`, validated `pydantic-settings` config (environment, log level, CORS origins; `*` rejected), global 500 handler that hides internals, `/docs` disabled in production, CORS limited to GET/POST.
- Multi-stage Dockerfile: `builder` → `dev` (reload, test deps) → `runtime` (default; slim, non-root `app` user, HEALTHCHECK, single uvicorn worker).
- Tests: 16 pytest tests (health, config validation, error handling, docs toggle, CORS).
- Verified: tests pass; runtime image 161 MB, ~49 MB RAM, healthcheck healthy, invalid config fails fast at startup.
- Switched test client dependency `httpx` → `httpx2` (Starlette deprecation). Security review flagged it as a possible typosquat; verified legitimate (imported by Starlette's own testclient; published by Pydantic, github.com/pydantic/httpx2; dev-only).
- Security review fix: removed `--forwarded-allow-ips "*"`; proxy headers now trusted only from `FORWARDED_ALLOW_IPS` (default `127.0.0.1`; set to the Traefik network in F7.1). Verified spoofed `X-Forwarded-For` is ignored by default.
- Added `src` to `ruff.toml` so `app.*` imports sort as first-party.
- PR raised against `main`; awaiting review.

### 2026-11-12: F0.1 repo setup
- Added `.gitignore`, `.editorconfig`, shared `ruff.toml` (incl. bandit security rules), `.pre-commit-config.yaml` (hygiene, ruff-check, black; versions pinned via autoupdate), `.env.example`, README.
- ESLint/Prettier hooks moved to F0.4 (they need the frontend's pinned dependencies); plan updated.
- Verified: `pre-commit run --all-files` passes; ruff and black confirmed working on a probe file.
- PR raised against `main`; awaiting review.

### 2026-11-12: Planning
- Drafted features and tiers; wrote `FEATURES.md`, `MVP-PLAN.md` and `DATA-STRATEGY.md`.
- Finalised the stack and database (Neon).
- Created this progress tracker and `CLAUDE.md` (Git rules).
- Added the development workflow, Feature Completion Checklist and per-feature breakdown (branches + commit messages) to `MVP-PLAN.md`.
- GitHub repo created; workflow changed to PR-per-feature against `main` (no `develop`).
- Initial commit of docs and `CLAUDE.md` pushed to `main`.
- **Next:** F0.1 `feature/repo-setup`.

---

## Known Issues / Open Questions

- Confirm whether Jolpica offers a bulk data dump (otherwise use a rate-limited API crawl). To check at the start of Phase 1 (F1.2).
- Set `FORWARDED_ALLOW_IPS` to the Coolify/Traefik proxy network (never `*`). To do in F7.1.
