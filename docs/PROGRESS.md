# ApexGPT — Development Progress

Tracks where development stands, so work can resume after any interruption.

**How to resume:** read **Current Status** and **Next Steps**, check the open phase's feature checklist, then review the latest **Session Log** entry.

**How to update:** when a feature passes the Feature Completion Checklist ([MVP-PLAN.md §5](./MVP-PLAN.md#5-development-workflow)) and its PR to `main` is raised, mark it `🔍 PR #<n>`. Tick it only after the user merges the PR. Update Current Status and Next Steps, and add a Session Log entry at the end of each work session. Record any change to an agreed decision in the Decision Log.

Related docs: [MVP-PLAN.md](./MVP-PLAN.md) · [FEATURES.md](./FEATURES.md) · [DATA-STRATEGY.md](./DATA-STRATEGY.md)

---

## Current Status

| | |
|---|---|
| **Current phase** | Phase 1: Structured data |
| **Current feature** | F1.5 `feature/readonly-db-role` (PR raised, awaiting review) |
| **Current branch** | `feature/readonly-db-role` |
| **Open PR** | #12 (F1.5) |
| **Repo** | https://github.com/RChaubey16/apexgpt |
| **Last updated** | 2026-11-12 |
| **Blockers** | None |

## Next Steps

1. User reviews and merges the F1.5 PR.
2. After merge: pull `main`, start **F1.6** `feature/structured-data-checks` (last Phase 1 feature).
3. Optional (user): in GitHub branch protection for `main`, require the **CI passed** check.

---

## Phase Overview

| Phase | Status | Started | Completed |
|---|---|---|---|
| Planning | ✅ Done | 2026-11-12 | 2026-11-12 |
| 0. Local foundation | ✅ Done | 2026-11-12 | 2026-11-12 |
| 1. Structured data | 🟡 In progress | 2026-11-13 | |
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
- [x] F1.1 `feature/f1-schema`: structured F1 schema · PR #8 merged
- [x] F1.2 `feature/jolpica-loader`: Jolpica loader 1950–2025 · PR #9 merged
- [x] F1.3 `feature/entity-aliases`: alias and lineage tables · PR #10 merged
- [x] F1.4 `feature/stats-views`: stats SQL views · PR #11 merged
- [ ] F1.5 `feature/readonly-db-role`: read-only role for LLM queries · 🔍 PR #12
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
| 2026-11-13 | F1 data source: Jolpica CSV dump (free, 14-day delay, non-commercial), not an API crawl | One ~15 MB download covers 1950–present; the API's 500 req/hour limit would make a crawl take hours |
| 2026-11-13 | F1 schema: Ergast-style flat tables; source IDs as primary keys (except `status`, `qualifying`); times as integer ms; `position` NULL when unclassified; results one row per car entry | Simple SQL for the LLM; idempotent reloads; handles 1950s shared drives |
| 2026-11-13 | Loader semantics follow Jolpica's own Ergast-compatible API (jolpica_api/ergastapi) | Our numbers match what that API reports (quali position = last session, standings = per-round rows, status = detail text) |
| 2026-11-13 | Loader = one-transaction sync: COPY to staging, delete stale races, upsert changed rows, delete stale facts; entities never deleted; scoped to the season range | Idempotent and atomic; safe to re-run; later alias tables can reference entities safely |
| 2026-11-13 | `ingestion/` is its own uv project (psycopg + pydantic-settings, stdlib urllib for downloads); schema owned by backend migrations | Matches the planned layout; no backend import coupling; minimal deps |
| 2026-11-13 | Aliases: normalised text, many-to-many, kinds name/surname/nickname; names generated from data, nicknames + lineage curated as CSV seeds keyed by `ref`; synced in the loader's transaction | One lookup table for F3.4; ambiguity kept explicit; seeds survive ID changes; editing a CSV + re-running applies it |
| 2026-11-13 | LLM role `apexgpt_llm_reader`: created NOLOGIN by migration (no password in code), SELECT on the v_* views only, role defaults statement_timeout 5s / lock_timeout 1s / idle-in-transaction 10s / read-only / 5 connections; login enabled by `python -m app.db.readonly_role` from READONLY_DATABASE_URL | Least privilege; credentials stay in env; defaults are a backstop, the SQL tool must still validate queries |
| 2026-11-13 | Stats views are plain (not materialized) views with `COMMENT ON` docs per view/column; fastest laps exposed as `fastest_laps_since_2004`; `race_starts` approximate alongside exact `race_entries` | Data is small (queries < 60 ms); comments let the SQL tool tell the LLM the caveats; column names prevent misreading incomplete data |
| 2026-11-13 | Poles = `results.grid = 1` (qualifying only exists from 1994) | Matches official pole counts across all eras |
| 2026-11-12 | CI: one GitHub Actions workflow, parallel jobs, single `CI passed` gate; actions pinned to commit SHAs; CI Postgres uses trust auth (no password literal) | One required check for branch protection; supply-chain safety; avoids secret-scanner false positives like the F0.3 GitGuardian alert |

---

## Session Log

Newest first.

### 2026-11-13: F1.5 read-only role for LLM queries
- PR #11 (F1.4) merged.
- Migration `0005`: role `apexgpt_llm_reader` (NOLOGIN, no superuser/createdb/createrole/inherit, connection limit 5), role defaults `statement_timeout=5s`, `lock_timeout=1s`, `idle_in_transaction_session_timeout=10s`, `default_transaction_read_only=on`; `USAGE` on `public` + `SELECT` on the four views only (views read tables with the owner's rights, so no table grants). Idempotent across databases on one server (roles are cluster-wide); downgrade revokes and drops the role only if no other DB still uses it.
- `python -m app.db.readonly_role`: validates READONLY_DATABASE_URL (user must be the role, password ≥ 16 chars, Neon needs 60+ bits), sets the password as a quoted literal + LOGIN via the admin URL, then connects as the role and reads a view. Never prints URLs/passwords; DB errors show the class only. New optional setting `READONLY_DATABASE_URL` (blank = unset, normalised, secret).
- Probed on the dev DB as the role: views readable; tables and alias tables `InsufficientPrivilege`; INSERT/CREATE refused; `pg_sleep(6)` cancelled at 5.0s.
- **Found and fixed:** `migrations/env.py` called `fileConfig()` with the default `disable_existing_loggers=True`, which silenced all app loggers whenever migrations ran in-process (surfaced by a caplog test). Now `False`.
- Tests: backend 190 (unit: credential validation, settings secrecy, error output; integration: role attributes/settings, grants are exactly the v_* views (fails if a new view isn't granted), every view readable, tables refused, writes/DDL refused even after `SET default_transaction_read_only = off`, no self-grant, login path on a throwaway role incl. a password with quotes/semicolons, missing role). Tests never change the real role's password. Ingestion 143 pass.
- Local: `.env` now has READONLY_DATABASE_URL with a random password; login enabled on the dev DB.
- PR raised against `main`; awaiting review.

### 2026-11-13: F1.4 stats views
- PR #10 (F1.3) merged.
- Migration `0004`: `v_race_winners`, `v_driver_career`, `v_season_summary`, `v_head_to_head_teammates`, each with `COMMENT ON VIEW`/`COLUMN` text (meanings + data caveats) for the F3.5 SQL tool. Static SQL (no string building). Downgrade drops them.
- Data findings that set the definitions: did-not-qualify entries aren't in the source; non-starts appear as "Withdrew"/"Did not start"/pre-race injuries, but formation-lap failures look like lap-1 retirements, so `race_starts` is approximate (exact `race_entries` alongside). Fastest-lap ranks only exist for 2004+ (plus 21 races in the 1950s) → `fastest_laps_since_2004`.
- Real-data checks (all match official figures unless noted): Hamilton 380 starts / 105 wins / 202 podiums / 104 poles / 7 titles; Schumacher 91 / 155 / 68 poles / 7 / 1,566 pts (starts 308 v official 306, documented); Senna 41 / 80 / 65 poles / 614 pts; Prost 51 / 106 / 33 / 798.5; Verstappen 71 wins, 4 titles; 2025 Norris by 2 over Verstappen; 2021 Verstappen by 8; 1997 runner-up Frentzen (Schumacher excluded); 1958 Hawthorn by 1, Vanwall constructors'; Senna v Prost 1988: qualifying 14-2, wins 8-7. Fangio's points 279.14 v official 277.64 (source's 1950s fractional points). Queries take < 60 ms.
- Tests: backend 158 (new hand-built dataset: shared 1950s win counted once, poles from grid, 1955 fastest lap excluded, withdrawal not a start or DNF, title only from final standings, season with no standings still listed, no constructors' champion without standings, teammate H2H both directions with qualifying-over-grid rule, documented views/caveat columns; schema tests now check views exist and are dropped on downgrade). Ingestion 143 still pass.
- Dev DB migrated to `0004`.
- PR raised against `main`; awaiting review.

### 2026-11-13: F1.3 entity aliases and constructor lineage
- PR #9 (F1.2) merged.
- Migration `0003` + models: `driver_aliases`, `constructor_aliases` (PK alias + entity id, `kind` name/surname/nickname, format check `^[a-z0-9]+( [a-z0-9]+)*$`, cascade on entity delete) and `constructor_lineage` (predecessor, successor, first season under the successor, note; season in the key so teams can return to an old identity).
- `ingestion/structured/aliases.py`: `normalise_alias` (NFKD + transliteration of ø/æ/ß/ł/…; non-alphanumerics → single spaces), seed reading/validation, and a set-diff sync (insert/update/delete) run at the end of the load transaction. Generated: every driver's full name + surname; every constructor's name + ref. Curated seeds (`structured/seeds/*.csv`, keyed by `ref`): 67 driver nicknames, 26 constructor nicknames, 33 lineage edges. Lineage is validated against race data (successor raced in the season; predecessor in that season or the one before). All 33 edges passed on real data.
- New CLI flag `--no-seeds`; seed problems (unknown refs, lineage not matching data) fail the whole load and roll it back.
- Real data: 1,701 driver aliases, 245 constructor aliases, 33 lineage edges; re-run is a no-op. Checked: "checo" → Pérez, "kimi" → Räikkönen + Antonelli, "schumacher" → Michael/Ralf/Mick, "silver arrows" → Mercedes, "lotus" → three Lotus teams; recursive query from Mercedes gives Tyrrell → BAR → Honda → Brawn → Mercedes.
- Tests: backend 143 (new tables in the drift/FK-index/compact-type checks; 14 more bad-row cases; multi-mapping, team return, alias cascade). Ingestion 143 (normalisation incl. DB-format check, real seed files valid, malformed seeds, sync of generated + curated rows, no-op re-sync, seed edits synced, unknown ref rolls back the whole load, lineage-vs-data checks, CLI `--no-seeds`).
- Dev DB migrated to `0003` and loaded with the real seeds.
- PR raised against `main`; awaiting review.

### 2026-11-13: F1.2 Jolpica loader
- PR #8 (F1.1) merged.
- New `ingestion/` uv project (Python 3.12; psycopg, pydantic-settings). `python -m structured`: download → verify → transform → load.
  - **Download:** reads the dump index, takes the free delayed CSV dump, streams it with SHA-256 + size checks, caches it as `data/jolpica/jolpica-csv-<hash>.zip`. https only; retries 429/5xx/network errors (honours `Retry-After`, capped at 60s); generic User-Agent; logs hosts only (the redirect is a signed S3 URL).
  - **Reader:** reads CSVs straight from the zip by column name; required columns are checked per table; member-size guard.
  - **Transform:** semantics copied from Jolpica's Ergast-compatible API code. Only races with results in the season range (skips future rounds); entities limited to referenced rows. Every bad value raises an error naming the table, row and column. Float artefacts in points (`1.1400000000000001`) round to 2 dp; real precision loss fails.
  - **Load:** one transaction, COPY into temp staging tables, `ON CONFLICT DO UPDATE ... WHERE IS DISTINCT FROM` (only changed rows touched), stale races/facts deleted within the season range, entities never deleted. Reports inserted/updated/deleted per table.
- The DB check constraints caught a real quirk on the first load: Jolpica uses `fastest_lap_rank = 0` for "no timed lap" (237 entries); now stored as NULL.
- Real data, 1950–2025: 76 seasons, 77 circuits, 817 drivers, 203 constructors, 136 statuses, 1,149 races, 25,873 results, 480 sprint results, 10,973 qualifying, 34,620 driver + 13,481 constructor standings, 12,192 pit stops. **12.7 MB** (budget ~25 MB). Full run ~9 s incl. download; a re-run changes nothing.
- Spot checks pass: Hamilton 105 wins, 1950 = 7 races, 2021 champion Verstappen (395.5 v 387.5), Schumacher 1997 excluded (no position), McLaren constructors' champion 2024 + 2025, Gasly's 1:14.279 fastest lap at Monaco 2019. **Found:** qualifying only exists from 1994 (Senna shows 3 quali P1s); `grid = 1` gives the official pole counts (Senna 65, Hamilton 104). Recorded for F1.4.
- Tests: 98 ingestion tests (fixture dump covering shared drives, two-session qualifying, cancelled/future/out-of-range rounds, exclusions, rank 0, float points; download retries, hash/size checks, cache; CLI; config secrecy) incl. 9 integration tests on real Postgres (first load, no-op reload, updates only touch changed rows, stale deletes + cascade, season scoping, full rollback on failure, status id stability, CLI end-to-end). Confirmed the sync test fails if stale-row deletion is disabled.
- CI: new **Ingestion tests** job (own Postgres service, schema via backend migrations, integration guard); added to the `CI passed` gate.
- Loaded the real data into the local dev DB.
- Not done (out of F1.2 scope): `ingestion/Dockerfile` (the plan's layout lists one; ingestion runs on the dev machine, so it can come later if needed).
- PR raised against `main`; awaiting review.

### 2026-11-13: F1.1 structured F1 schema
- PR #7 (Phase 0 docs) merged; Phase 1 started.
- **Resolved open question:** Jolpica publishes CSV/SQL database dumps (`https://api.jolpi.ca/data/dumps/download/`). Free tier: delayed 14 days, non-commercial use, no auth. Downloaded the delayed CSV dump (14.7 MB zip, SHA-256 matched the listing): 18 CSVs in Jolpica's own session-based schema (`round`, `session`, `sessionentry`, `roundentry`, `teamdriver`, `driverchampionship`, …), covering 1950–2026. F1.2 will load from it instead of crawling.
- Dump facts that shaped the schema: race session entries can repeat a driver (shared drives, 83 cases) and share a position (105 cases); every entry has a position, with `is_classified` marking unclassified ones; status is free text (139 distinct values); points include halves (shared drives); qualifying is split into `QB` (pre-2006 single session) and `Q1/Q2/Q3`; standings are per session (sprint + race); fastest lap times only exist in the lap table (the loader will derive them).
- Added ORM models (`backend/app/db/models/f1.py`) and migration `0002`: `seasons`, `circuits`, `drivers`, `constructors`, `status`, `races`, `results`, `sprint_results`, `qualifying`, `driver_standings`, `constructor_standings`, `pit_stops`. Compact types, check constraints as boundary validation (ranges, positivity, code length), FK indexes, `ON DELETE CASCADE` from races. `lap_times` deliberately absent.
- Alembic `env.py` now imports `app.db.models` so autogenerate sees the tables.
- Tests: 119 passing. New unit tests check compact types, no `*_text` columns, Wikipedia URLs and that every FK is indexed; this caught a missing `qualifying.constructor_id` index (and an initial test bug that made the check vacuous). New integration tests: migration matches models (`compare_metadata`; confirmed it fails on a changed column type), round trip, half points, shared drives, cascade delete, downgrade to 0001, and 29 bad-row cases rejected.
- Verified: the compose backend ran `0001 -> 0002` on start; 12 tables; `/health/ready` ok.
- PR raised against `main`; awaiting review.

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

- Set `FORWARDED_ALLOW_IPS` to the Coolify/Traefik proxy network (never `*`). To do in F7.1.
- F3.5 SQL tool: the role's timeout/read-only defaults can be changed by the session (`SET`, `set_config()`), so the tool must only run validated single SELECTs on the v_* views (reject SET/set_config/multiple statements) and should also set its own `SET LOCAL statement_timeout`. Add `COMPOSE_READONLY_DATABASE_URL` for the backend container then.
- F7.2 (Neon): confirm the migration's `CREATE ROLE` works as the Neon owner role and run `python -m app.db.readonly_role` against Neon.
