# ApexGPT — Development Progress

Tracks where development stands, so work can resume after any interruption.

**How to resume:** read **Current Status** and **Next Steps**, check the open phase's feature checklist, then review the latest **Session Log** entry.

**How to update:** when a feature passes the Feature Completion Checklist ([MVP-PLAN.md §5](./MVP-PLAN.md#5-development-workflow)) and its PR to `main` is raised, mark it `🔍 PR #<n>`. Tick it only after the user merges the PR. Update Current Status and Next Steps, and add a Session Log entry at the end of each work session. Record any change to an agreed decision in the Decision Log.

Related docs: [MVP-PLAN.md](./MVP-PLAN.md) · [FEATURES.md](./FEATURES.md) · [DATA-STRATEGY.md](./DATA-STRATEGY.md)

---

## Current Status

| | |
|---|---|
| **Current phase** | Phase 0: Local foundation |
| **Current feature** | F0.1 `feature/repo-setup` (PR raised, awaiting review) |
| **Current branch** | `feature/repo-setup` |
| **Open PR** | [#1](https://github.com/RChaubey16/apexgpt/pull/1) (F0.1) |
| **Repo** | https://github.com/RChaubey16/apexgpt |
| **Last updated** | 2026-11-12 |
| **Blockers** | None |

## Next Steps

1. User reviews and merges the F0.1 PR.
2. After merge: pull `main`, start **F0.2** `feature/backend-skeleton`.

---

## Phase Overview

| Phase | Status | Started | Completed |
|---|---|---|---|
| Planning | ✅ Done | 2026-11-12 | 2026-11-12 |
| 0. Local foundation | 🟡 In progress | 2026-11-12 | |
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

### Phase 0: Local Foundation
- [ ] F0.1 `feature/repo-setup`: monorepo tooling and pre-commit hooks · 🔍 PR #1
- [ ] F0.2 `feature/backend-skeleton`: FastAPI skeleton with `/health`
- [ ] F0.3 `feature/database-setup`: pgvector database with Alembic
- [ ] F0.4 `feature/frontend-skeleton`: Next.js shell with health check
- [ ] F0.5 `feature/docker-compose-setup`: full compose stack with memory limits
- [ ] F0.6 `feature/ci-pipeline`: CI for lint, tests and Docker builds
- [ ] **Phase done check:** `docker compose up` works and the frontend shows a healthy backend

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

---

## Session Log

Newest first.

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
- Confirm Neon's Postgres major version before pinning the local `db` image. To check in F0.3.
