# ApexGPT — Development Progress

Tracks where development stands, so work can resume after any interruption.

**How to resume:** read **Current Status** and **Next Steps**, check the open phase's feature checklist, then review the latest **Session Log** entry.

**How to update:** when a feature passes the Feature Completion Checklist ([MVP-PLAN.md §5](./MVP-PLAN.md#5-development-workflow)) and its PR to `main` is raised, mark it `🔍 PR #<n>`. Tick it only after the user merges the PR. Update Current Status and Next Steps, and add a Session Log entry at the end of each work session. Record any change to an agreed decision in the Decision Log.

Related docs: [MVP-PLAN.md](./MVP-PLAN.md) · [FEATURES.md](./FEATURES.md) · [DATA-STRATEGY.md](./DATA-STRATEGY.md)

---

## Current Status

| | |
|---|---|
| **Current phase** | Phase 5: Frontend MVP (in progress) |
| **Current feature** | F5.6 UI theme (PR in review) |
| **Current branch** | `feature/ui-theme` |
| **Open PR** | F5.6 responsive F1 dark theme |
| **Repo** | https://github.com/RChaubey16/apexgpt |
| **Last updated** | 2026-11-24 |
| **Blockers** | None |

## Next Steps

1. User reviews and merges the F5.6 PR (and looks at it in a browser, on a phone too if possible).
2. **Phase 5 close-out**: the phase done check end to end on merged `main` (the plan's Phase 5 items), then Phase 6 on the user's go-ahead.
3. Optional (user): add `EMBEDDING_CACHE_DIR=../data/models` to `.env`, so the host reuses the downloaded models.
4. Optional (user): in GitHub branch protection for `main`, require the **CI passed** check.

---

## Phase Overview

| Phase | Status | Started | Completed |
|---|---|---|---|
| Planning | ✅ Done | 2026-11-12 | 2026-11-12 |
| 0. Local foundation | ✅ Done | 2026-11-12 | 2026-11-12 |
| 1. Structured data | ✅ Done | 2026-11-13 | 2026-11-13 |
| 2. Narrative corpus | ✅ Done | 2026-11-13 | 2026-11-17 |
| 3. Retrieval + LLM | ✅ Done | 2026-11-21 | 2026-11-22 |
| 4. Chat API | ✅ Done | 2026-11-22 | 2026-11-23 |
| 5. Frontend MVP | 🟡 In progress | 2026-11-23 | |
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

### Phase 1: Structured F1 Data ✅
- [x] F1.1 `feature/f1-schema`: structured F1 schema · PR #8 merged
- [x] F1.2 `feature/jolpica-loader`: Jolpica loader 1950–2025 · PR #9 merged
- [x] F1.3 `feature/entity-aliases`: alias and lineage tables · PR #10 merged
- [x] F1.4 `feature/stats-views`: stats SQL views · PR #11 merged
- [x] F1.5 `feature/readonly-db-role`: read-only role for LLM queries · PR #12 merged
- [x] F1.6 `feature/structured-data-checks`: sanity checks · PR #13 merged
- [x] **Phase done check:** sanity checks pass; structured data < ~25 MB (verified in F1.6: 30/30 pass on real data locally and in CI, 11.5 MB)

### Phase 2: Narrative Corpus
- [x] F2.1 `feature/wiki-fetcher`: MediaWiki fetcher with cache · PR #15 merged
- [x] F2.2 `feature/article-selection`: selection rules + `topics.yaml` · PR #16 merged
- [x] F2.3 `feature/article-cleaner`: Wikipedia cleaner · PR #17 merged
- [x] F2.4 `feature/chunker`: section-based chunker with metadata · PR #18 merged
- [x] F2.5 `feature/embedding-pipeline`: fastembed pipeline + `chunks` table · PR #19 merged
- [x] F2.6 `feature/size-guard`: DB size guard · PR #20 merged
- [x] ~12–15k chunks: **14,581**
- [x] Under ~120 MB: chunks table **59.5 MB**; whole database **80.2 MB**
- [x] "Senna Prost Suzuka collision" returns the 1989/1990 Japanese GP chunks: **partly met; the user accepted carrying it into Phase 3** (2026-11-17). It becomes an acceptance test for F3.1/F3.2.
  - Vector search alone: #1 is the 1990 Japanese GP; the 1989 Japanese GP race report is #15.
  - Ad-hoc fusion of vector and full-text results (RRF, k=60, not the F3.1 implementation): #1 "Prost–Senna rivalry > 1989 > Decisive clash at Suzuka", #2 "… > 1990: Second clash at Suzuka", #6 the 1990 Japanese GP. The 1989 Japanese GP article's own chunks are not in the top 10.

### Phase 3: Retrieval & LLM Layer ✅
- [x] F3.1 `feature/hybrid-search`: hybrid search with RRF · PR #24 merged. **Acceptance:** "Senna Prost Suzuka collision" returns chunks of both the 1989 and the 1990 Japanese Grand Prix articles in the top results (carried from Phase 2). **Met:** 1990 Japanese GP #1, 1989 Japanese GP race report #6 (top 10; `pytest -m corpus`).
- [x] F3.2 `feature/reranker`: reranker · PR #25 merged. **Acceptance:** the Senna/Suzuka test holds in the top 5 after reranking. **Met:** 1990 Japanese GP #1, 1989 Japanese GP race report #4 (`pytest -m corpus`).
- [x] F3.3 `feature/llm-client`: LLM client with fallback · PR #26 merged. Verified live on Groq (answer, tool call, stream); Gemini/OpenRouter not yet (no keys).
- [x] F3.4 `feature/entity-resolution`: entity resolution · PR #27 merged. 30/30 labelled questions (`pytest -m corpus`).
- [x] F3.5 `feature/stats-tool`: text-to-SQL stats tool · PR #28 merged. Live: Groq wrote correct SQL for 8/8 questions; `pytest -m llm` 5/5.
- [x] F3.6 `feature/knowledge-search-tool`: knowledge search tool · PR #29 merged. Live: Groq's own search terms found the right articles 3/3.
- [x] F3.7 `feature/answer-orchestrator`: tool-calling orchestrator · PR #30 merged
- [x] **Phase done check:** the three CLI test questions are answered correctly (2026-11-22, live: `pytest -m llm tests/live/test_phase3_done_check.py` 3/3, and by hand with `python -m app.answer`)

### Phase 4: Chat API ✅
- [x] F4.1 `feature/chat-endpoint`: streaming chat endpoint · PR #32 merged
- [x] F4.2 `feature/conversation-memory`: follow-up handling · PR #33 merged
- [x] F4.3 `feature/feedback-endpoint`: feedback endpoint · PR #34 merged
- [x] F4.4 `feature/rate-limiting-cache`: rate limiting + cache · PR #35 merged
- [x] F4.5 `feature/structured-logging`: structured file logging · PR #36 merged
- [x] **Phase done check** (the plan's Phase 4 items, end to end on merged `main` in the dev container, 2026-11-23): streamed answer; follow-up condensed ("Who replaced him as race director?" → "Who replaced Michael Masi as race director?", answered by Gemini while Groq was rate limited); repeat served from the cache in 2 ms; feedback 201; 429 on the 4th request after 3 in the minute; one JSON log line per event. Caveat: "Explain Abu Dhabi 2021" came back without citations in this run (the model used only the stats tool; Known Issues, F6).

### Phase 5: Frontend MVP
- [x] F5.1 `feature/chat-ui`: streaming chat interface · PR #38 merged
- [x] F5.2 `feature/answer-rendering`: markdown, tables, citations · PR #39 merged
- [x] F5.3 `feature/starter-questions`: starter question cards · PR #40 merged
- [x] F5.4 `feature/chat-history`: local conversation history · PR #41 merged
- [x] F5.5 `feature/answer-actions`: copy + feedback actions · PR #42 merged
- [ ] F5.6 `feature/ui-theme`: responsive F1 dark theme · 🔍 PR raised

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
| 2026-11-12 | Free LLMs only via LiteLLM (Groq → Gemini → OpenRouter) | No paid AI services. *Library changed on 2026-11-21 (see below)* |
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
| 2026-11-13 | Wikipedia fetch: `action=parse` HTML (cleaned later in F2.3) + batched `action=query` revision checks; serial, throttled, `maxlag=5`; JSON-per-article cache keyed by requested title; `WIKI_USER_AGENT` required (user supplies contact details) | Rendered HTML keeps the structure the cleaner needs (tables, infoboxes, citations are marked up); cheap incremental refresh; follows Wikimedia API etiquette without sending personal details by default |
| 2026-11-13 | Shared `ingestion/common/http.py` (`open_url`) for both fetchers | One implementation of https-only, retries and Retry-After |
| 2026-11-14 | Article selection: titles from each entity's `wikipedia_url` (never guessed); depth as a policy (`full`/`race`/`circuit`/`lead`), sections chosen by the cleaner (F2.3); notable/major rules use the stats views; major constructor applied per article over all constructor rows sharing it; topics upgrade already-selected articles to full | Matches DATA-STRATEGY §2b; selection stays independent of article layout; Cooper-Climax/Cooper-Maserati etc. are one team |
| 2026-11-14 | Selection resolved on Wikipedia before writing a manifest (`data/narrative/selection.json`): missing + disambiguation pages dropped, redirects merged by page id; curated titles (topics, overrides) must resolve or the run fails | One cache entry per page (no duplicate chunks); curation mistakes fail loudly, source-data gaps don't |
| 2026-11-14 | `narrative/title_overrides.csv` (kind, ref, title) for stale source URLs; validated like the structured seeds | 34 source URLs now hit disambiguation/missing pages (incl. Tony Brooks, Jaguar, Toyota, Surtees); refs survive ID changes |
| 2026-11-14 | Topic metadata: one group per topic (`rivalry`, `safety`, `controversy`, `iconic_race`, `regulations`, `car`, `concept`, `people`, `history`) + optional driver/constructor/circuit refs and one season | Becomes the chunk's `topic` + id filters (F2.4); refs checked against the data, also in the weekly real-data workflow |
| 2026-11-14 | Cleaner: lxml (6.1.3); walk the parser output in order tracking the heading path; drop all tables + page furniture by tag/class, boilerplate sections by name/pattern, table notes by pattern | Fast (2,349 articles in ~95 s); heading paths give the chunker section boundaries and labels |
| 2026-11-14 | `race` depth = everything except session/entry-list sections (denylist), not a list of narrative headings | Real articles name narrative sections many ways ("Report", "Race", "Aftermath", "Diffuser ban and controversy", "Death of … and inquiries"); an allowlist lost them |
| 2026-11-14 | `circuit` depth also keeps layout/track description and fatal-accident sections | Answers "what's the track like" and crash questions; small (77 articles) |
| 2026-11-14 | Cleaned corpus in `data/narrative/articles.jsonl` (selection metadata + page/revision/URL + sections); a run with any missing/stale/unusable article writes nothing | The chunker needs one input; a partial corpus never replaces a complete one |
| 2026-11-14 | Corpus is ~3.7M tokens (≈8k chunks at ~450 tokens), below the planned 12–15k chunks | Stripping is more aggressive than estimated; leaves room under the size budget. Chunk size/overlap decided in F2.4 |
| 2026-11-14 | Chunks: target ~450 / max 500 estimated tokens including the `title > section` heading (not 400–600); ~50-token sentence overlap within a section; lead alone; small subsections of one top-level section packed | bge-small-en-v1.5 truncates input after 512 tokens. Sizes estimated at 1.4 tokens/word (bge tokenizer on this corpus: mean 1.28, p99 1.39) so the chunker needs no model download; 3 of 14,581 chunks are 2–17 tokens over in reality, F2.5 can check exactly |
| 2026-11-14 | Chunks inherit article-level metadata only (no per-chunk name tagging) | Mention tagging is ambiguous ("Hill", "Brabham"); question-side entity resolution is F3.4 |
| 2026-11-16 | `chunks` keyed by (pageid, chunk_index) with a `content_hash` (BLAKE2b-128 of model + embedded text); sync re-embeds only new text, reuses vectors of moved chunks, commits per 256-row batch, deletes stale rows last | First full embed takes ~37 min on CPU: it must be resumable, and later re-runs should take seconds |
| 2026-11-16 | Full-text index on `to_tsvector('english', title \|\| ' ' \|\| text)` instead of `text` alone | Continuation chunks rarely repeat the race/driver name; the title restores it. Same cost (expression index, no stored column) |
| 2026-11-16 | `season`, `race_id`, `circuit_id` are real foreign keys (ON DELETE SET NULL); `driver_ids`/`constructor_ids` are checked by the pipeline before writing | Arrays can't carry foreign keys; a structured reload must never delete chunks |
| 2026-11-16 | Chunks embedded with fastembed's passage form (no prefix); questions must use `query_embed` (bge query instruction) with the same model | bge-small is asymmetric; the model name is stored in every hash, so a model change re-embeds everything |
| 2026-11-17 | Size guard in `ingestion/common/size_guard.py` (plan said `ingestion/size_guard.py`); thresholds in decimal MB (700 / 900 × 10⁶ bytes) | `common/` is the existing shared package. Decimal MB is the stricter reading of Neon's 1 GB |
| 2026-11-17 | Guard checks before a load and before each commit (structured: inside the one transaction → rollback; chunks: before every batch) | Catches a load that would cross the limit, not only one that starts past it |
| 2026-11-17 | Phase 2 closed with the search criterion partly met (1990 Japanese GP #1; 1989 race report #15 with vector search alone); carried into F3.1/F3.2 as an acceptance test | User's decision. The right content is found (rivalry/biography sections), and ranking is Phase 3's job |
| 2026-11-13 | Sanity checks run inside the load transaction (failure = rollback) and standalone; real-data checks in a separate weekly/path-filtered workflow, outside the `CI passed` gate | A bad dump can't replace good data; real data is verified in CI without making unrelated PRs depend on Jolpica's uptime |
| 2026-11-13 | LLM role `apexgpt_llm_reader`: created NOLOGIN by migration (no password in code), SELECT on the v_* views only, role defaults statement_timeout 5s / lock_timeout 1s / idle-in-transaction 10s / read-only / 5 connections; login enabled by `python -m app.db.readonly_role` from READONLY_DATABASE_URL | Least privilege; credentials stay in env; defaults are a backstop, the SQL tool must still validate queries |
| 2026-11-13 | Stats views are plain (not materialized) views with `COMMENT ON` docs per view/column; fastest laps exposed as `fastest_laps_since_2004`; `race_starts` approximate alongside exact `race_entries` | Data is small (queries < 60 ms); comments let the SQL tool tell the LLM the caveats; column names prevent misreading incomplete data |
| 2026-11-13 | Poles = `results.grid = 1` (qualifying only exists from 1994) | Matches official pole counts across all eras |
| 2026-11-12 | CI: one GitHub Actions workflow, parallel jobs, single `CI passed` gate; actions pinned to commit SHAs; CI Postgres uses trust auth (no password literal) | One required check for branch protection; supply-chain safety; avoids secret-scanner false positives like the F0.3 GitGuardian alert |
| 2026-11-21 | Hybrid search = RRF (k 60) of three lists: vector (weight 1.0), all-words full-text per chunk (0.5), and all-words per **article**, represented by its nearest chunk (0.5); 50 candidates each; at most 2 chunks per article | Chosen on 15 labelled questions (session log 2026-11-21). The article list is what puts the 1989 Japanese GP in the top results: no single chunk has all of "Senna Prost Suzuka collision" |
| 2026-11-21 | Corrects 2026-11-16: fastembed's `query_embed` adds **no** instruction for bge-small (same vector as `passage_embed`), so the backend prepends bge's retrieval instruction itself | Measured. With the instruction the expected articles ranked higher on the labelled set |
| 2026-11-21 | Accent folding with a text search configuration `apex_english` (`unaccent` → `english_stem`), with the GIN index rebuilt on it (migration 0007); not an `unaccent()` wrapper function | A regconfig is immutable, so no wrapper is needed, and documents and queries fold the same way. `unaccent` is a trusted extension, available on Neon |
| 2026-11-21 | A year in the question → season filter that keeps untagged chunks (`season = ANY(...) OR season IS NULL`); no new metadata indexes | Only race chunks have a season, so a strict filter would drop biographies and rivalries. Every list already uses an index (HNSW with pgvector 0.8 iterative scans, GIN): ~10 ms total on 14.5k chunks |
| 2026-11-21 | Search-quality tests on the real corpus behind a `corpus` pytest marker (`CORPUS_DATABASE_URL`, read-only), outside CI | CI has no corpus; the acceptance test still needs the real data and model |
| 2026-11-21 | **Reranker: `Xenova/ms-marco-MiniLM-L-6-v2`, not `bge-reranker-base`** (user's decision, changes the 2026-11-12 plan) | Measured on the 15 labelled questions. bge-reranker-base: 13/15 in the top 5, Senna/Suzuka failed (1989 race #12), ~1.6 s per question, ~2 GB peak RAM (backend limit 768 MB). MiniLM-L-6: 15/15 when blended, ~0.2 s (Mac), +170 MB. MiniLM-L-12, jina tiny/turbo and bge-v2-m3-int8 were no better and slower |
| 2026-11-21 | Reranker order is blended with the hybrid order (RRF, reranker ×2), not used alone; 10 candidates → top 5; documents scored one at a time | Blended: 15/15 in the top 5, reranker alone: 14/15. 10, 12, 15, 20 and 30 candidates gave identical results, and reranking costs ~70 ms per candidate on one CPU. Batches raised peak RAM by ~240 MB with no speed gain |
| 2026-11-21 | A failing reranker falls back to the hybrid order (warning logged) instead of failing retrieval | A model problem should degrade answers, not break chat |
| 2026-11-21 | `ONNX_THREADS` setting (default 1) for both models | ONNX Runtime starts a thread per host core, and a container sees all of them under a 1-CPU quota: retrieval took 16.4 s instead of 0.7 s in the dev container |
| 2026-11-21 | **LLM client uses the official openai SDK against each provider's OpenAI-compatible API, not LiteLLM** (user's decision, changes the 2026-11-12 plan) | Measured: importing LiteLLM 1.110.2 added ~213 MB RAM and 3.1 s (backend ~400 → ~610 MB of 768 MB); openai 3.57 added ~44 MB and 0.2 s. Groq, Gemini and OpenRouter are all OpenAI-compatible, and the fallback/retry logic is ours either way. A non-compatible provider would need its own adapter |
| 2026-11-21 | Groq model `openai/gpt-oss-120b`; every provider's model is a setting | Llama 3.3 70B is no longer offered on the key's free tier (11 models listed). gpt-oss-120b made correct tool calls in ~0.6 s (qwen3.8-27b: 1.4 s) |
| 2026-11-21 | Fallback rules: timeouts/connection/5xx retry the same provider (`LLM_MAX_RETRIES`, default 1, backoff 0.5 s/1 s), every other API error or an unusable response goes to the next provider; SDK retries off | Free-tier 429 limits last minutes to days, so retrying is pointless; a 400 can be provider-specific (Groq `tool_use_failed`); our own loop keeps it testable |
| 2026-11-21 | Streaming is in the client (F3.3), falling back only before the first token | F4.1 needs it; once text is shown, switching provider would repeat or contradict it |
| 2026-11-22 | Entity resolution keeps ambiguity: each mention lists up to 5 candidates, ordered by active-in-a-named-season, then match strength (driver full name > nickname > constructor name = surname > circuit), then wins and races | The orchestrator (F3.7) can show or use the alternatives. Ranking a team name and a surname equally lets prominence decide teams named after drivers ("McLaren" the team, "Prost" the driver) |
| 2026-11-22 | Single-word aliases that are everyday words in F1 questions (curated list of 36, e.g. pace, speed, era, driver, force) match only when capitalised; "March"/"May" never match alone; rare-word names (senna, hunt, button, lotus) always match | 145 single-word aliases are dictionary words. Precision first: tagging "top speed" as Scott Speed misleads the LLM; lowercase "senna" must still work |
| 2026-11-22 | Circuits resolved from the `circuits` table (ref, locality, name minus generic leading/trailing words) plus a small curated map; no country aliases | No circuit alias table exists. Countries would tag "drivers from Argentina" as the Buenos Aires circuit |
| 2026-11-22 | Entity index held in memory (~2,000 aliases, +7 MB), reloaded every 6 hours, keeping the old index if a reload fails | ~20 µs per question with no DB round trip; loader updates appear without a restart |
| 2026-11-22 | Stats SQL validated with Postgres's own parser (`pglast` 8.9, PG 18 grammar) against allowlists of node types, relations (the 4 views + CTEs), functions, cast types and SQL value functions; not regexes or a denylist | INTO, FOR UPDATE, DELETE-in-CTE and set_config all parse as a top-level SELECT, so only a full-tree check is safe; default-deny means unknown constructs are rejected. +25 MB, 0.4 s import |
| 2026-11-22 | The tool runs SQL regenerated from the validated tree (deparsed), with the row limit set in the tree, through the driver's cursor with no parameters | No gap between what's checked and what runs; through SQLAlchemy, `ILIKE '%monza%'` failed (`%` read as a placeholder) |
| 2026-11-22 | Defence in depth: validation, then the read-only role, then a READ ONLY transaction with the tool's own `SET LOCAL statement_timeout` 3 s / `lock_timeout` 1 s; 50-row cap (51 fetched to flag truncation); its own 2+1 connection pool | Resolves the F1.5 Known Issue (role defaults can be changed by a session) |
| 2026-11-22 | Errors for the LLM: rejection reasons, and for SQLSTATE classes 42/22/21/0A plus timeouts Postgres's primary message only; other database errors become a generic "unavailable" | The LLM can fix its own query; no hosts, context lines or credentials leak |
| 2026-11-22 | The tool description carries the views' `COMMENT ON` text and a rule against `LIMIT 1` for "most/best" questions | Live test: "most wins at Monza" came back as Hamilton alone, but Hamilton and Schumacher share the record (5); with the rule, 5/5 twice |
| 2026-11-22 | One tool interface: `name`, `definition()`, `call(arguments) -> ToolOutcome(payload, ok, sources)`; expected failures become error payloads, never exceptions | The orchestrator (F3.7) treats every tool the same and always has something to send back to the model |
| 2026-11-22 | Knowledge results: 5 chunks with short source ids numbered by the caller (S1, S2, … across searches), text cut at 2,000 chars, URLs kept out of the payload | Short ids are easier for the model to cite; ~1,600 tokens per call matters on the free tier; URLs aren't needed to reason, only to display |
| 2026-11-22 | `search_f1_knowledge(query, seasons?)`: seasons only (no driver/team filters) | Only race chunks carry metadata (F3.1); driver/team filters would drop the biographies and rivalries that answer most questions |
| 2026-11-22 | The orchestrator lives in `app/answer/` (with its prompts), not `app/llm/` as the plan's layout said | It depends on the LLM client, both tools and entity resolution; inside `app/llm/` the low-level client would import everything above it |
| 2026-11-22 | Tool loop: up to 3 rounds / 4 tool calls, then one request without tools; entity hints in the user message with the views' own values (`driver_ref = '…'`, `circuit_name = '…'`) | Bounded cost on the free tier; hints with exact column values stopped wasted queries (`circuit_name ILIKE '%Abu Dhabi%'` → 0 rows) |
| 2026-11-22 | Citations normalised before checking (`【S3】`, `[S3†L2]`, `[S1, S2]` → `[S3]`, `[S1][S2]`); unknown ids removed; `Answer.sources` = the cited sources in order | gpt-oss writes full-width, suffixed citations; without this the Hunt/Lauda answer listed no sources |
| 2026-11-22 | Output reservations 900 (tool rounds) / 1,000 (final); stats description omits `*_id` and `wikipedia_url` columns; client waits once (≤ `LLM_RATE_LIMIT_WAIT_SECONDS`, default 20) when every provider is rate limited | Groq's free tier: 8,000 tokens/minute for gpt-oss-120b, counting `max_tokens`. One narrative answer was ~8.5k tokens with 1,500-token reservations |
| 2026-11-22 | Fallback defaults changed: Gemini `gemini-3.1-flash-lite`, OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free` | Live checks once the keys were added: `gemini-2.5-flash` is closed to new users (404), `gpt-oss-120b:free` is gone (404). Newer Gemini flash models were overloaded (503, timeouts, 19–34 s); lite made a correct tool call in 2 s, nemotron in 1.3 s |
| 2026-11-22 | Every round is streamed with the tools offered (`LLMClient.stream_turn`): tool calls are collected inside the attempt (fallback still possible), text streams; `stream()` is a wrapper over it | No second request to stream the final answer (the free tier can't afford it); all three providers stream tool calls and usage (measured) |
| 2026-11-22 | Tool calls keep provider extras and are echoed back; tool history from another provider is flattened to text (`prepare_messages`) | Gemini 3 rejects function calls without its own `thought_signature` (400), even its own when the field was dropped; flattened text works everywhere (measured). Fixed a latent F3.3/F3.7 bug: multi-round answers on Gemini failed |
| 2026-11-22 | `CitationFilter` checks citations while streaming: hold from `[`/`【` to the closing bracket (≤ 40 chars), normalise or drop, then release; whitespace is only touched where a marker was dropped | An invalid `[S9]` never reaches the client; the old cleaner also collapsed all double spaces, which broke nested markdown lists |
| 2026-11-22 | SSE events: the plan's `token`, `citation`, `table`, `done`, `error`, plus `tool` (started/finished). Stream always ends with `done` or `error`; request body is strict (`extra="forbid"`) | Tool rounds take 1–4 s with nothing else to show; a strict body means `history` only works once F4.2 handles it |
| 2026-11-23 | Follow-ups: `history` (≤ 20 messages, user/assistant only, ≤ 8,000 chars each) is used only to condense the question, in one request without tools (temperature 0, ≤ 400 output tokens); the standalone question then goes through the whole pipeline; the answering model never sees the history | Entity resolution and the tools need names, not "he"/"that year". Keeping the history out of the answer rounds saves tokens on every round (Groq's 8k/minute) and keeps client-supplied text out of the grounded prompt |
| 2026-11-23 | Condense input: last 6 messages, assistant answers cut to 600 chars without `[S#]` markers; no condensing when the history has no user message; an LLM failure or unusable rewrite answers the question as asked (logged) | Bounded cost (~450 tokens, 0.4–0.9 s measured on Groq); the direct answer comes first in our answers; a literal answer beats an error. 400 output tokens because gpt-oss's reasoning counts against `max_tokens` (it used 64–212) |
| 2026-11-23 | Feedback table (migration 0008): rating, question, answer excerpt (first 500 chars, cut at a word; the API accepts the full answer up to 8,000), optional provider/model, `created_at`; check constraints on every field; no IP or user identifier; not granted to the LLM role | Matches the plan's fields; provider/model let F6 score the fallback providers from real ratings; the server cuts the excerpt so the client can send the answer as it has it |
| 2026-11-23 | 90-day retention = an indexed DELETE in the same transaction as every save, plus `python -m app.feedback purge` for a scheduled job (F7.3); 90 days is a constant, not a setting | No background timer that would wake Neon; rows still expire when no feedback arrives once the weekly job runs it |
| 2026-11-23 | Feedback database errors → 503 with a fixed message (error class logged only) | Same rule as the chat errors: no host or driver details reach the client |
| 2026-11-24 | Markdown with `react-markdown` 10.1 + `remark-gfm` 4.0 (pinned); no raw HTML, unsafe URLs dropped (default transform, plus our own `cite:` scheme); per-element Tailwind classes instead of the typography plugin | Answers carry paraphrased Wikipedia text, so HTML must never render. The model writes markdown tables itself. +~156 KB raw client JS |
| 2026-11-24 | Citation chips: `[S3]` → a numbered chip linking to the source, only for ids the backend sent as `citation` events (the text can't forge one); a Sources list (title › section) with the CC BY-SA note once the answer is complete | Chips stay honest: an invented id is plain text. The list doubles as the Wikipedia attribution |
| 2026-11-24 | `table` events behind a collapsed "Show the data (N rows)" disclosure, not a second table | Seen live: the model already writes its own table into the text (sometimes cut with "…"); the exact rows stay one click away without showing everything twice |
| 2026-11-24 | Answer actions: Copy gives the answer's markdown plus "Sources: [S1] Title › Section — URL"; 👍/👎 once per answer, recorded on the answer (and in the saved chat) only after the backend stores it; the question sent is the standalone one the backend answered (`done.question`), else the one asked; fields clipped to the backend's limits | Pasted [S#] markers stay meaningful. The backend has no update, so one vote per answer avoids duplicate rows (a reload can't re-vote). Clipping means a long answer never 422s |
| 2026-11-24 | Chat history: one versioned `localStorage` key (`apexgpt.conversations`, `version: 1`), at most 50 chats; every write re-reads the key and changes one chat; what is read back is validated (a bad chat is dropped alone; source links must be http(s)); on a full quota the oldest other chats are dropped, else the chat carries on unsaved with a notice | No login in the MVP. Re-reading keeps two tabs from wiping each other's chats; validation because storage can hold anything (old versions, edits, corruption) |
| 2026-11-24 | A visit opens on a new chat (saved ones listed beside it); a chat is saved with its first question and as answers end, not per token; leaving mid-answer stops it and keeps the text as "stopped" | Reloading mid-answer can't resume a stream anyway; saving per token would rewrite the whole key dozens of times a second |
| 2026-11-24 | The page is a fixed-height app (`h-dvh`): sidebar and conversation scroll separately, composer pinned at the bottom; on phones the chats are a drawer | A sidebar beside a page-scrolling chat needs sticky offsets tied to the header height; internal scrolling doesn't |
| 2026-11-24 | Citation markers with zero-width/format characters (U+200B–U+200F, U+2060–U+2064, U+FEFF, soft hyphen) are recognised (backend `fix:` commit on this branch) | Seen live: gpt-oss wrote `[\u200bS1\u200b]`, so sources were dropped. The chips depend on it, so it shipped with F5.2 as its own commit |
| 2026-11-23 | Chat client: `fetch` POST + our own SSE parser (not `EventSource`, not a library); every event validated against the backend contract; unknown event types skipped; typed `ChatError` kinds (rate_limited, invalid_request, unreachable, http_error, bad_response, interrupted, answer_error); an abort rethrown as AbortError | `EventSource` is GET-only; the parser is ~40 lines and is tested over 1–64-byte chunks, split UTF-8 and CRLF. Skipping unknown events lets the backend add events without breaking deployed frontends |
| 2026-11-23 | UI state is a pure reducer (`conversation.ts`); `history` = finished exchanges only (failed/stopped/empty answers left out), last 20 messages, each ≤ 8,000 chars | Testable without React; a half answer would mislead the follow-up rewrite |
| 2026-11-23 | After a 429 the Send button stays disabled for `Retry-After` seconds; no automatic retry | An automatic retry would spend the user's next request without them asking |
| 2026-11-23 | Logging: console stays text; `LOG_FILE` adds JSON lines via `RotatingFileHandler` (size-based, 10 MB × 5, settings); stdlib only, no new dependency; `configure_logging` replaces only its own handlers (fixes the `basicConfig(force=True)` Known Issue) | Size rotation bounds disk use on a small VPS; text on the console keeps `docker logs` readable; other handlers (pytest capture, uvicorn) survive |
| 2026-11-23 | One `chat` event per request, logged by the route when the stream ends (`ok` / `error` / `disconnected`), plus `feedback` and `rate_limited` events; no client IPs in the file | The route is the only place that knows the outcome, including disconnects. Questions are what the plan asks to log; addresses aren't needed |
| 2026-11-23 | An unwritable `LOG_FILE` → a console warning, the app keeps running (settings tolerate an unreadable path too) | Losing logs must not take the API down. Found in the image check: `Path.is_dir()` raised `PermissionError` in the settings validator and stopped startup |
| 2026-11-23 | **Rate limits with `limits` (5.8, slowapi's engine) as a FastAPI dependency, not slowapi's decorator** (changes the plan's library) | slowapi's `@limiter.limit` needs a module-level limiter, created before `create_app` reads settings, so every app in a process shares one limiter's counters (tests leak into each other). A per-app limiter from settings is ~60 lines; `limits` was already what slowapi would install (+1 dependency, 49 ms import) |
| 2026-11-23 | Per-IP moving windows in memory; defaults chat `6/minute;100/day`, feedback `30/minute;500/day` (settings, blank = off); 429 + `Retry-After` (exposed via CORS) before the endpoint runs, invalid bodies count too; key = `request.client.host`, never `X-Forwarded-For` directly | One uvicorn worker, so no shared store. Groq's free tier is ~8k tokens/minute for everyone (~2 answers), so a per-IP cap is about stopping scripts, not fairness. uvicorn already resolves the client from trusted proxies only |
| 2026-11-23 | Answer cache: LRU of recorded events (tokens merged), 256 entries / 24 h (settings), keyed by the folded standalone question; stored only when every tool was available and every call worked; stored before `done` is yielded; `done.cached`, and tokens/calls in `done` are the request's own | Data covers finished seasons, so a day loses little. Keying after condensing lets follow-ups hit. A degraded answer (stats DB down) must not be repeated for a day. `answer()` stops at `done`, which would have skipped a write placed after it (found by the tests) |
| 2026-11-23 | New SSE event `question` (when the follow-up was rewritten) and `question` in `done` | The UI can show how a follow-up was understood, and the answer can be checked against it |
| 2026-11-24 | Theme as Tailwind `@theme` tokens; components may not use the default palette (a test enforces it, and WCAG AA contrast for every text/surface pair) | One place to change the look; the old muted greys failed AA, and a test stops that from coming back |

---

## Session Log

Newest first.

### 2026-11-24: F5.6 responsive F1 dark theme
- PR #42 (F5.5) merged.
- **Built:**
  - `globals.css`: theme tokens in Tailwind's `@theme` (surfaces `background`/`surface`/`raised`/`hover`, `line`/`control`, text `foreground`/`soft`/`muted`, F1 red `accent`/`accent-strong`/`accent-text`, success/warning/danger), `checkered` and `speed-stripes` utilities, one global `:focus-visible` ring, dark scrollbars, `color-scheme: dark`, and reduced motion.
  - Every component moved from raw `zinc`/`red`/`amber` classes to the tokens. Header: racing-stripe mark, italic wordmark, checkered band. Empty chat: a "Lights out" heading over the starter cards (red-edged). Answers: a rail that is red while streaming, uppercase table headers. Send: a slanted red button. Active chat: a red stripe.
  - Layout `viewport`: `themeColor` (the page background), `colorScheme: dark`, `viewportFit: cover`; the header, composer and drawer pad themselves clear of safe areas. Larger touch targets (chat list, answer actions, mobile bar); 16 px inputs on phones.
- **Contrast fix:** the old muted text (`zinc-500` ≈ 4.1:1, `zinc-600` ≈ 2.6:1 on the page) was below WCAG AA; all text tokens now meet 4.5:1 on every surface.
- **Tests:** frontend 217 (+36 in `theme.test.ts`: the contrast formula, every text/surface pair, the 3:1 UI colours, the browser bar colour, and no default-palette classes in components). Mutation checks (4): a dimmer muted colour, a dimmer control border, a `text-zinc-500` in a component and a different `themeColor` all fail it. Lint, typecheck, prettier and `next build` clean; the built CSS has every new utility.
- **Looked at (headless Chrome on the rebuilt dev stack):** desktop 1400×900 empty and with a live answer (2023 wins, tables, actions); phone 390 and 320 wide (no sideways scroll, header wraps), and the phone drawer. The Next.js dev indicator ("N") overlaps the composer only in dev.

### 2026-11-24: F5.5 copy and feedback actions
- PR #41 (F5.4) merged.
- **Built:**
  - `src/lib/feedback.ts`: the `POST /api/feedback` client (trims and clips to 500/8,000 characters by code point, omits empty provider/model, 10 s timeout, safe messages for 429 with its delay, 503 with the backend's message, other statuses, bad bodies and network errors). `retryAfter`/`detail` are now shared from `chat.ts`.
  - `src/components/AnswerActions.tsx`: Copy ("✓ Copied" for 2 s, "Couldn't copy" without a clipboard) for finished and stopped answers; 👍/👎 (`aria-pressed`, disabled while sending and once rated, "Thanks for the feedback.", errors inline with a retry) for finished ones only.
  - The rating is a `rate` action on the answer (`feedback: "up" | "down"`), stored and validated with the saved chat.
- **Fix found by a new test:** the reducer returned a new state for a no-op update (a late event after Stop, a second rating), so React re-rendered and the change was reported for saving. It now returns the same state.
- **Live check (dev stack):** the CORS preflight from `http://localhost:3000` for `POST /api/feedback` allows it, and a feedback body like the client's was stored (201, id 4). The frontend container was rebuilt. Not yet clicked in a real browser.
- **Tests:** frontend 181 (+29: client 11, actions 13, reducer 1, storage 2, Chat 2 — incl. the clipboard, the standalone question, sending/disabled, retry after failure, a recorded rating). Lint, typecheck, prettier and `next build` clean.
- **Mutation checks (21):** all caught except an unreachable guard against a second click (the buttons are disabled then), which was removed.

### 2026-11-24: F5.4 local conversation history
- PR #40 (F5.3) merged.
- **Built:**
  - `src/lib/history.ts`: the stored chats (versioned key, validation on read, 50 at most, quota handling, re-read before every write so tabs don't clobber each other, titles from the first question, rename/delete).
  - `src/lib/useStoredConversations.ts`: the list as React state through `useSyncExternalStore` (empty on the server, so hydration matches; re-reads on this tab's writes and on the `storage` event).
  - `src/components/ConversationList.tsx`: New chat, open, inline rename (Enter/Escape) and inline delete confirmation (no browser dialogs).
  - `src/components/ChatApp.tsx`: the sidebar (a drawer on phones) beside `<Chat key>`; saving, the "couldn't be saved" notice, and "this browser can't save chats".
  - `Chat.tsx`: `initialMessages` and `onMessagesChange` (on each question, when an answer ends, and on unmount if changed; not per token). The page became a fixed-height layout.
- **Build fix during the feature:** `next build` (Cache Components) refused `Date.now()` during render (the first chat id). A new chat now has no id until its first save, which runs in an effect; `Chat`'s key is a counter, so getting an id doesn't remount it.
- **Tests:** frontend 152 (+46: storage 26, Chat reporting 4, ChatApp flows 16, incl. tab sync, quota, no storage, delete while answering, the drawer). The shared test fakes moved to `src/test/`. Lint, typecheck, prettier and `next build` clean.
- **Mutation checks (26):** all caught after adding tests for 4 survivors (the write-side 50 cap, a renamed title kept on later saves, New chat on an empty chat keeping the draft, the blur after Escape). One more "survivor" had only edited a comment (the real line is caught by 5 tests), and an id map that no test could reach was removed instead.
- **Dev stack:** the frontend container was rebuilt and serves the new layout. Not yet looked at in a real browser.

### 2026-11-24: F5.3 starter question cards
- PR #39 (F5.2) merged.
- **Chose the questions live first:** six candidates were asked against the dev backend. All six answered correctly: Abu Dhabi 2021 and Senna–Prost (knowledge, with citations); Hunt 1976 (both tools, 5 citations); most titles, most constructor wins, most wins in 2023 (stats). Per-season poles were avoided (Known Issue).
- **Built** `frontend/src/components/StarterQuestions.tsx`: six cards (title + question) in a responsive grid, shown on an empty chat in `Chat.tsx`. Picking one asks it at once, leaves a typed draft alone, and the cards are disabled when the frontend is misconfigured.
- **Dev stack:** the frontend container was rebuilt and serves the cards. Not yet looked at in a real browser.
- **Tests:** frontend 106 (+6: cards and titles, pick, disabled, question limits, asking from Chat, misconfigured). Lint, typecheck, prettier and `next build` clean. Mutation checks (6): 5 caught; the survivor was an unreachable guard in `Chat.tsx`, which was removed.

### 2026-11-24: F5.2 markdown, table and citation rendering
- PR #38 (F5.1) merged.
- **Looked at real answers first:**
  - The model writes its own markdown tables (so `table` events would duplicate them).
  - Citations: "Explain Abu Dhabi 2021" streamed **no citation events** although the knowledge search ran. The text had `[\u200bS1\u200b]`: zero-width spaces inside the marker, which the backend's filter didn't match.
- **Backend fix** (separate `fix:` commit): the citation filter strips zero-width/format characters inside markers. +3 test cases and a streaming case; reverting the fix fails 3 tests. Live after the fix: 5 citation events, clean `[S1]` markers.
- **Built** (`frontend/src/components/AnswerContent.tsx`):
  - Markdown + GFM via react-markdown (no raw HTML, safe URLs, external links in a new tab with `noopener noreferrer nofollow`), scrollable tables.
  - Citation chips for known ids, and the Sources list with the CC BY-SA note.
  - The "Show the data" disclosure (column labels, number formatting, notes).
  - Used by `Chat.tsx` in place of the plain text.
- **Real answers rendered through the components** (jsdom; the browser tools weren't available):
  - Abu Dhabi 2021: 3 sources, 6 chips, the model's 2 tables, no leftover `[S#]` or `**`.
  - Monza: its table, plus 5 exact rows behind the disclosure, and no citations (stats only).
- **Dev stack:** the frontend container was rebuilt with the new packages and the page serves 200. Not yet looked at in a real browser.
- **Tests:**
  - Frontend 100 (+16: markdown, GFM tables, chips, unknown and late citations, sources only when complete, the disclosure, raw HTML, `javascript:`/`data:` links, external link attributes, forged chips, a real answer, helpers). Lint, typecheck, prettier and `next build` clean.
  - Backend 748 unit passing.
  - Mutation checks (8 frontend: unknown ids linked, no URL sanitising, forged chips, opener kept, no GFM, sources while streaming, row count, raw column names): all caught.

### 2026-11-23: F5.1 streaming chat interface (Phase 5 started)
- User gave the go-ahead for Phase 5. PR #37 (Phase 4 close-out) merged.
- **Built** (`frontend/src/`):
  - `lib/chat.ts`: `streamChat`, `parseFrame`, `readFrames`, event validation, and `ChatError`.
  - `lib/conversation.ts`: the reducer, `historyFor` and `isAnswering`.
  - `components/Chat.tsx`:
    - the message log (`role="log"`, polite live region) and composer (Enter / Shift+Enter, counter, limit);
    - Stop; tool status; "Answering: …"; error and rate-limit handling; "Answered from cache";
    - abort on unmount.
  - `app/page.tsx`: a compact header with the status pill (still calls `/health/ready` on load) above the chat.
- **Real backend:**
  - The browser tools weren't available in this session, so the real `streamChat` and reducer ran under Node against the dev stack.
  - "Who won the 1988 championship?" fresh in 2.0 s. The follow-up "How many races did he win that year?" sent 2 history messages and was rewritten to "How many races did Ayrton Senna win in 1988?" (2.8 s).
  - On the rerun, both came from the cache (1 ms; 0.57 s for the follow-up, which is the rewrite request).
  - The CORS preflight from `http://localhost:3000` allows POST + Content-Type.
  - **Not yet looked at in a real browser.**
- **Production image:** `next build` passes; the frontend image builds (330 MB).
- **Tests:** frontend 84 (+54: the client over every chunk size, CRLF, split UTF-8, each HTTP outcome, malformed events, aborts before and during the stream; the reducer and history rules; the component: streaming, follow-up history, Stop, errors, the rate-limit block, the counter, no double send, cached, misconfigured, abort on unmount). Lint, typecheck and prettier clean.
  - Mutation checks (11: UTF-8 not streamed, split CRLF, unknown events fatal, abort reported as unreachable, early end accepted, failed answers in history, history unbounded, late events applied, no rate-limit block, no abort on unmount, no history sent): all caught.

### 2026-11-23: Phase 4 closed
- PR #36 (F4.5) merged: **all Phase 4 features (F4.1–F4.5) are merged.**
- Phase 4 delivers `POST /api/chat`:
  - SSE events (token, citation, table, tool, question, done, error);
  - follow-up condensing from client history;
  - per-IP rate limits;
  - an answer cache;
  - one structured log event per request.

  It also adds `POST /api/feedback` with 90-day retention, and JSON-lines file logging.
- Done check run end to end on merged `main` (see the Phase 4 checklist). Backend unit tests 741 passing on `main`.
- Plan change made with the user along the way: `limits` instead of slowapi's decorator (Decision Log).
- Carried into later phases (Known Issues):
  - narrative answers sometimes skip the knowledge search (F6);
  - per-season stats missing from the views (F3.5/F6);
  - the feedback purge in the weekly workflow (F7.3);
  - the log volume, `FORWARDED_ALLOW_IPS` and the models in the image (F7.1).
- Phase 5 not started; waiting for the user's go-ahead.

### 2026-11-23: F4.5 structured file logging
- PR #35 (F4.4) merged.
- **Built:**
  - `app/core/logging.py`: `JsonFormatter` (`ts`/level/logger/message, `extra` fields, `error` + `traceback`, repr for values JSON can't hold) and `configure_logging` (console + optional rotating JSON file, only its own handlers replaced, warns if the file can't be opened).
  - The `chat` event in `/api/chat` (outcome, question, standalone question, history size, tools, provider, model, sources, tokens, calls, cache, latency); `feedback` and `rate_limited` events.
  - Settings `LOG_FILE`, `LOG_FILE_MAX_MB`, `LOG_FILE_BACKUPS`; docker compose writes `data/logs/`; the runtime image has `/app/logs` owned by `app`.
  - Tests no longer re-add pytest's capture handler (the old workaround): it survives `create_app` now.
- **Bug found in the image check, fixed:** an unreadable `LOG_FILE` path (`/root/...` as user `app`) crashed settings validation (`Path.is_dir()` raises `PermissionError`), so the app didn't start. Now it warns and runs.
- **Dev container:** a fresh and a cached chat answer and a feedback save each wrote one JSON line to `data/logs/apexgpt.log`, with no client addresses. The test feedback row was deleted.
- **Runtime image:** writes `/app/logs/apexgpt.log` as `app`; 694 MB.
- **Tests:**
  - Backend 741 unit (+21: format, extras, exceptions, handlers kept and replaced, rotation, unwritable and unreadable paths, settings, the chat event's fields and outcomes incl. disconnect, the file end to end with no client address), 157 integration, 74 corpus, live `pytest -m llm` 22/22, all passing. Ingestion 532 passing.
  - Mutation checks (11: removing all handlers, handlers piling up, extras dropped, only missing directories tolerated, multi-line JSON, no rotation, no `disconnected` outcome, no log on disconnect, standalone question dropped, the settings crash, `LOG_FILE` ignored): all caught.

### 2026-11-23: F4.4 rate limiting and answer cache
- PR #34 (F4.3) merged.
- **Plan change:** `limits` as a dependency instead of slowapi's decorator. slowapi 0.1.10 is current and light, but needs a module-level limiter, so apps and tests would share counters (Decision Log).
- **Built:**
  - `app/core/rate_limit.py`: `parse_limits`, a per-app `RateLimiter` (moving windows, memory), and the `rate_limit(scope)` dependency (429 + `Retry-After`).
  - Applied to `/api/chat` and `/api/feedback`; CORS exposes `Retry-After`.
  - `app/answer/cache.py`: `cache_key`, `coalesce`, and the thread-safe `AnswerCache` (LRU + TTL).
  - Orchestrator: lookup after condensing; record and store worthwhile answers; replay with `cached`. `done.cached`.
  - Settings: `RATE_LIMIT_CHAT`, `RATE_LIMIT_FEEDBACK`, `ANSWER_CACHE_SIZE`, `ANSWER_CACHE_TTL_SECONDS` (validated at startup), in `.env.example` and docker compose.
- **Bug found by the tests, fixed before commit:** the cache write ran after `done` was yielded, so `answer()` (and any caller stopping at `done`) never stored anything.
- **Docker:** the runtime image builds (694 MB, +3 MB) and imports the new modules.
- **Dev container, real HTTP:** "Who has the most wins at Monza?" took 3.3 s fresh, and "who has the most wins at monza" took **6 ms** from the cache (0 tokens). The 7th request in a minute got a 429 with `Retry-After: 57`; `/health` was unaffected; 125 MB.
- **Tests:**
  - Backend 720 unit (+43: keys, LRU, TTL, threads, merging, what is and isn't cached, replays incl. follow-ups and tables; limits parsing, windows, per-client, per-scope, blank = off, forwarded headers ignored, CORS), 157 integration, 74 corpus, all passing. Ingestion 532 passing.
  - Live `pytest -m llm`: 21/22 passing in each of the first two full runs. The narrative test failed 2 of the 9 times it ran (the model used only the stats tool; Known Issues). That isn't from this change: a fresh answer runs the same code, and the test builds a new app (empty cache, fresh limiter). It passed 7 of 9, including 4/4 in a row at the end.
  - Mutation checks (11: caching everything, ignoring missing tools, the cached flag, keying on the raw follow-up, LRU, TTL, NFKC, the limiter, trusting `X-Forwarded-For`, feedback unlimited, `Retry-After` hidden): all caught.

### 2026-11-23: F4.3 answer feedback endpoint
- PR #33 (F4.2) merged.
- **Built:**
  - Migration 0008 and `app/db/models/feedback.py`: the `feedback` table with check constraints and a `created_at` index.
  - `app/feedback/`: `save_feedback` (insert + purge, one transaction), `purge_expired`, `excerpt`, and CLI `python -m app.feedback purge`.
  - `POST /api/feedback` (strict body → 201 `{"id"}`; 422; safe 503).
- **Dev container:** migration 0008 ran at startup; 201 and 422 over HTTP; the purge CLI ran in the container (the test row was deleted afterwards).
- **Tests:**
  - Backend 677 unit (+31: the contract, 422s, 503 without details, excerpts, the purge statement, the CLI), 157 integration (+13: the endpoint on real Postgres, the 90-day boundary, purge on save and its rollback, constraints, the LLM role can't read it, downgrade; the model-vs-migration check covers the new table), 74 corpus, all passing. Ingestion 532 passing.
  - Mutation checks (91-day retention, no purge on save, no word cut, only some database errors caught, extra fields allowed, migration drift, CLI without commit): all caught.

### 2026-11-23: F4.2 follow-up question handling
- PR #32 (F4.1) merged.
- **Built:**
  - `app/answer/followups.py`: `HistoryMessage`, `validate_history`, the condense prompt and `transcript` (last 6 messages, trimmed answers without markers), `parse_rewrite` (first line, labels and quotes stripped, normalised), and `condense` (falls back to the question as asked).
  - Orchestrator: `stream(question, history)` / `answer(question, history)`; a `QuestionEvent` when rewritten; `Answer.asked`; the condense request's tokens and call are counted.
  - `/api/chat`: optional `history` (strict `ChatMessage` model), the `question` event and `done.question`.
- **Live (Groq), 6 conversations:**
  - "How many poles did he get that year?" → "… Ayrton Senna get in 1988?"; "And at Silverstone?" → "Who has the most wins at Silverstone?"; "which of them had more wins?" → "Which of James Hunt and Niki Lauda …".
  - Standalone questions and an injection attempt in the history came back unchanged.
  - 0.4–0.9 s, 214–237 prompt + 64–212 completion tokens each.
- **Dev container, real HTTP:** a follow-up streamed `question` first, then the stats tool, answer done in 4.9 s, 125 MB. The answer was wrong (7 poles, the real count is 13): the stats views have no per-season poles (Known Issues), not a condensing problem.
- **Tests:**
  - Backend 646 unit (+38: condensing, cleaning, transcript, history validation, orchestrator follow-ups, the API's history contract and 422s), 144 integration (+1: a condensed follow-up through the real stats tool), 74 corpus, live `pytest -m llm` 22 (+1: a follow-up end to end), all passing. Ingestion 532 passing.
  - Mutation checks (resolving or answering the raw question, markers kept, whole history sent, no fallback on an unusable rewrite or an outage, no `question` event, history dropped by the API): all caught.

### 2026-11-22: F4.1 streaming chat endpoint (Phase 4 started)
- User gave the go-ahead for Phase 4.
- **Measured first, on all three providers:**
  - streaming with tools works, and the tool-call deltas carry ids;
  - `stream_options.include_usage` works;
  - a final request with tool messages but no tools works on Groq/OpenRouter, but **Gemini returned 400** ("missing thought_signature").
  - Gemini also rejected its *own* call once the signature field was dropped. The full echo and flattened text both worked.
- **Built:**
  - `LLMClient.stream_turn` (`Turn`, tool-call fragment assembly, usage, text-then-tools); `stream()` rebuilt on it.
  - `ToolCall.extra` (provider fields, echoed back) and `prepare_messages` (cross-provider history as text).
  - `Orchestrator.stream()` events (tool / table / token / citation / done), with `answer()` collecting them.
  - `CitationFilter` (streaming); `Orchestrator.close()`.
  - `POST /api/chat` (SSE, strict request, error events), wired into `create_app` (built once; lazy).
- **Dev container, real HTTP via uvicorn:**
  - "Explain Abu Dhabi 2021" streamed incrementally: first event 0.86 s, first token 4.8 s, done 5.3 s, 4 citations.
  - Groq was rate limited, so **Gemini ran both rounds**: its own tool call was echoed back with the signature. That would have failed before this change.
- **Tests:**
  - Backend 608 unit (+73: `stream_turn`, flattening, extras; orchestrator events; the citation filter in 1/2/3/7-char chunks; the SSE contract, errors, 422s), 143 integration (+2: `/api/chat` with the real stats tool as the read-only role), 74 corpus, all passing; live `pytest -m llm` (`/api/chat` + the done check). Ingestion 532 passing.
  - Mutation checks (flattening, stream extras, echoed extras, streamed tool validation, marker lookahead, held markers, error event): all caught. The lookahead one needed new chunk-boundary tests first.

### 2026-11-22: Phase 3 closed
- PR #30 (F3.7) merged: **all Phase 3 features (F3.1–F3.7) are merged, and the done check passes** (the three CLI questions, by hand and live).
- Phase 3 delivers:
  - hybrid search (vector + full-text + article lists, RRF, accent folding, season filters);
  - MiniLM-L-6 reranking (blend ×2, top 5);
  - the LLM client (openai SDK; Groq → Gemini → OpenRouter, with retries, fallback, streaming and short rate-limit waits);
  - entity resolution;
  - the validated text-to-SQL stats tool on the read-only role;
  - the knowledge search tool;
  - the grounded, cited answer orchestrator (`python -m app.answer`).
- Plan changes made with the user along the way (all in the Decision Log):
  - MiniLM-L-6 instead of bge-reranker-base;
  - the openai SDK instead of LiteLLM;
  - `openai/gpt-oss-120b` on Groq;
  - new Gemini/OpenRouter fallback models.
- Carried into Phase 4 and later (Known Issues): streaming the final reply after tool calls (F4.1), free-tier token limits, fallback answer quality (F6), and baking the models into the production image (F7.1).
- `main` synced. Phase 4 not started; waiting for the user's go-ahead.

### 2026-11-22: F3.7 answer orchestrator — Phase 3 done check passed
- **Built:**
  - `app/answer/`:
    - `prompts.py`: the grounded system prompt and entity hints;
    - `orchestrator.py`: resolve names → tool loop with limits → final no-tools round → citation check;
    - `build_orchestrator()` and the CLI `python -m app.answer`.
  - LLM client: wait-once-and-retry on short rate limits (`LLM_RATE_LIMIT_WAIT_SECONDS`); `parse_duration` for Groq's reset headers.
- **Done check, by hand and live (`pytest -m llm`, 3/3):**
  - "Who has the most wins at Monza?" → Hamilton and Schumacher, 5 each (table).
  - "Explain Abu Dhabi 2021" → the title decider: 369.5 points each, Latifi's crash, only 5 lapped cars unlapped, last-lap pass, protest, Masi replaced; cited.
  - "How did Hunt beat Lauda in 1976 and what were the final points?" → Nürburgring crash and return, the Fuji decider, Hunt 3rd → 69–68; both tools, cited.
- **Found on the way, all fixed:**
  - Groq's 8k tokens/minute limit counts `max_tokens`, so one answer could exceed it: smaller reservations, a leaner stats description, the wait-and-retry.
  - Once the Gemini/OpenRouter keys were added, both default models returned 404: new defaults, chosen by live tool-call tests.
  - gpt-oss's `【S3†…】` citations left the source list empty: normalisation.
  - A wasted query (`ILIKE '%Abu Dhabi%'`): hints now give exact column values.
  - Unrequested "Missing details" paragraphs and query explanations: prompt rules.
- **Dev container:** stats question in 1.4 s (104 MB); narrative question in 7.7 s. Groq hit its limit mid-answer and Gemini lite finished with 5 citations; peak 405 MB of 768 MB.
- **Tests:**
  - Backend 535 unit (+53: orchestrator loop, limits, hints, failures, citations, CLI; rate-limit waits and header parsing), 141 integration, 74 corpus, all passing; live `pytest -m llm` incl. the done check. Ingestion 532 passing.
  - Mutation checks (citation normalisation, final round without tools, source numbering, tool-call limit, unknown citations, wait limit, single retry): each caught.

### 2026-11-22: F3.6 knowledge search tool
- **Built:**
  - `app/tools/base.py`: `Tool` protocol, `ToolOutcome`, `Source`.
  - `app/tools/knowledge.py`: `KnowledgeTool` (argument validation, numbered sources, text cap, error payloads); `build_knowledge_tool()`.
  - `StatsTool` gained `name` / `definition()` / `call()` on the same interface.
- **Real corpus:**
  - The acceptance query gets both Japanese GPs; Abu Dhabi 2021, the 1976 German GP with a season filter, and the 1976 Japanese GP for Hunt/Lauda all come back.
  - ~6,600 characters per call.
  - In the dev container: 731 ms median per search, peak 387 MB.
- **Live (Groq):** the model chose its own search terms for 3 questions; all found the expected articles and its arguments validated.
- **Tests:**
  - Backend 482 unit (+37), 141 integration (+1: the tool over real Postgres), 74 corpus (+5), all passing. Ingestion 532 passing.
  - Mutation checks (source offset, text cap, season range, URL in payload): each caught.
- **Note:** on the host, models were re-downloaded because `.env` has no `EMBEDDING_CACHE_DIR` (it predates the setting); added to Next Steps.

### 2026-11-22: F3.5 stats tool
- **Setup on this machine:** `python -m app.db.readonly_role` enabled the read-only role's login here (it had never been run on this machine's database).
- **Built** (`backend/app/tools/`):
  - `sql_guard.py`: pglast parse, full-tree allowlists, LIMIT set in the tree, deparse.
  - `stats.py`: `StatsTool.run`, executed as the role in a read-only transaction with its own timeouts, JSON-safe values, payload for the LLM, error classes.
  - `schema()` from `COMMENT ON`, `tool_definition()`, and CLI `python -m app.tools.stats`.
  - docker compose passes `COMPOSE_READONLY_DATABASE_URL`.
- **Validator:** 6 real queries pass. 23 attacks are rejected with messages the LLM can use: INTO, FOR UPDATE, DELETE in a CTE, set_config, pg_sleep, query_to_xml, ::regclass, current_user, catalogs, raw tables in subqueries, functions in FROM, TABLESAMPLE, $1, LIMIT (SELECT …), other databases, COPY, EXPLAIN, and more.
- **Bugs found while trying it on the real views, both fixed:**
  - `%` in `ILIKE '%monza%'` broke queries sent through SQLAlchemy.
  - Raw psycopg errors were not classified.
- **Live text-to-SQL (Groq gpt-oss-120b, real tool description):**
  - 8/8 questions got correct SQL at the first attempt.
  - The "most wins at Monza" test caught `LIMIT 1` hiding the Hamilton/Schumacher tie, so I added a rule to the description; `pytest -m llm` then passed 5/5, twice.
  - The free tier's per-minute limit was hit once (Known Issues).
- **Container:** the stats tool as the role, Monza query 3 ms; peak 376 MB with retrieval loaded.
- **Docker:** runtime image builds, healthy, non-root, 691 MB (+41 MB: pglast).
- **Tests:**
  - Backend 445 unit (+111), 140 integration (+12: as the role via SET ROLE, the % and quote literals, truncation, one-line errors, schema comments, the validator's views = the role's grants, the read-only transaction and timeout), 69 corpus (+8: known answers, the 3 s timeout stopping a triple cross join on the real data), all passing. Ingestion 532 passing.
  - Mutation checks (node allowlist, function allowlist, unknown tables, large LIMIT kept, original SQL run instead of deparsed, SELECT INTO): each caught.
- Resolved the F1.5 Known Issue on session-changeable role defaults.

### 2026-11-22: F3.4 entity resolution
- **Built** (`backend/app/retrieval/`):
  - `normalise.py`: the loader's `normalise_alias`, copied, with a test that compares both on 18 samples.
  - `entities.py`:
    - in-memory `EntityIndex` built from the alias tables and `circuits` (with curated circuit names);
    - `EntityResolver`: longest-match scan, the everyday-word rules, ranking, 6-hour reload that keeps the old index on failure;
    - CLI `python -m app.retrieval.entities`.
- **Data checks:**
  - 2,068 aliases.
  - Ambiguous surnames: "taylor" → 4 drivers, "hill" → 3 (+ Embassy Hill team), "schumacher" → 3; "kimi" is two drivers.
  - 145 single-word aliases are dictionary words; 36 are everyday F1-question words and were curated into `COMMON_WORDS`.
  - Circuits: generic words are stripped only at the ends, so Imola never becomes "ferrari". Countries were left out.
- **Evaluation:** 30 labelled questions.
  - 19/21 on the first run: one labelling mistake, and "Prost" picked the Prost GP team over Alain Prost.
  - The ranking fix (team name = surname, prominence decides) took it to 21/21.
  - The 9 questions added afterwards passed unchanged.
- **Performance:** index load 88 ms (Mac) / 37 ms (container), resolve ~20 µs, +7 MB.
- **Tests:**
  - Backend 334 unit (+53), 128 integration (+4: the index SQL on real Postgres), 61 corpus (+31: the 30 questions and the curated circuit names), all passing. Ingestion 532 passing.
  - Mutation checks (everyday words, season activity, longest-first, team-name rank, months): all caught. Longest-first needed two new tests ("Red Bull Ring", "Kimi Räikkönen") before it was.
  - Fixed while testing: `load_entity_index` no longer rolls back the caller's session.
- **Docs:** README section, DATA-STRATEGY note, Decision Log, Known Issues.

### 2026-11-21: F3.3 LLM client
- **Two plan changes, both decided by the user after measurements:**
  - openai SDK instead of LiteLLM (+44 MB vs +213 MB RAM; 0.2 s vs 3.1 s import).
  - LiteLLM was checked first: 1.110.2 is past the compromised 1.82.7/1.82.8 PyPI releases. It was removed again before committing.
  - Groq's Llama 3.3 70B is gone from the free tier, so the default is `openai/gpt-oss-120b`, chosen after a live tool-call test.
- **Built** (`backend/app/llm/`):
  - `providers.py`: Groq → Gemini → OpenRouter, keys optional.
  - `client.py`: `LLMClient.complete` (text + tool calls) and `.stream`, with our own retries and fallback, request validation and response validation.
  - `build_llm_client(settings)`; CLI `python -m app.llm`.
  - Settings: three keys (blank = off), a model per provider, timeout, retries.
  - docker compose passes all of them to the backend.
- **Live checks (Groq):**
  - CLI answer in 632 ms, and streaming works.
  - `pytest -m llm`: 3/3 (answer, tool call, stream); Gemini/OpenRouter skipped (no keys).
  - In the dev container: retrieval + a grounded Groq answer to the Senna/Suzuka question in 863 ms; peak 394 MB of 768 MB.
- **Tests:**
  - Backend 281 unit (+71), 124 integration, 30 corpus, all passing. Ingestion 532 passing.
  - Mutation checks (429 retried, unknown tool accepted, mid-stream error swallowed, SDK retries left on): each caught.
- **Docker:** the runtime image builds, is healthy and runs non-root; 650 MB (was 612 MB).
- **Docs:** README LLM-client section and stack row, `.env.example`, MVP-PLAN (stack, phase text, layout, F3.3 row), Decision Log, Known Issues.

### 2026-11-21: F3.2 reranker
- **Built** (`backend/app/retrieval/`):
  - `reranker.py`: MiniLM-L-6 cross-encoder via fastembed, loaded lazily under a lock, scoring one document at a time; scores are validated (one finite score per document).
  - `retriever.py`: `KnowledgeRetriever`: 10 hybrid candidates → rerank → blend with the hybrid order (RRF, reranker ×2) → top 5. Falls back to the hybrid order if the reranker fails.
  - `build_retriever(settings)`: the entry point for the F3.6 knowledge tool.
  - CLI reranks by default; `--no-rerank` shows the hybrid order.
  - `ONNX_THREADS` setting (default 1); docker compose sets it.
- **Model choice (user decided after the measurements):** every fastembed reranker was run on the 15 labelled questions, with 20 candidates, each model in its own process:

  | Model | Top 5 | Senna | Per question | Peak RAM |
  |---|---|---|---|---|
  | none (hybrid) | 13 | ❌ | — | 262 MB |
  | MiniLM-L-6 | 14 | ✅ | 0.36 s | 1,275 MB* |
  | MiniLM-L-12 | 13 | ❌ | 0.72 s | 1,435 MB* |
  | jina v1 tiny / turbo | 12 / 13 | ❌ | 0.31 / 0.45 s | ~1.5 GB* |
  | bge-reranker-base (plan) | 13 | ❌ | 1.57 s | 2,035 MB* |
  | bge-v2-m3-int8 | 14 | ❌ | 4.47 s | 2,850 MB* |

  \*Batch of 20. MiniLM-L-6 at batch 1: 430 MB, 0.18 s.
- **Tuning** MiniLM-L-6 (batch size, candidates, reranker alone vs blended): blended ×2 gives 15/15 in the top 5 at every candidate count from 10 to 30.
- **Container check** (dev compose, 1 CPU, 768 MB):
  - The first run took 16.4 s per question: 10 ONNX threads under a 1-CPU quota.
  - `threads=1` and 10 candidates: **0.71 s median** (0.84 s max) warm, 1.0 s cold (both models load), peak 396 MB.
- **Tests:**
  - Backend 210 unit (+36), 124 integration (+1: retriever over real Postgres with a fake reranker), corpus 30 (+15: reranked top 5), all passing. Ingestion 532 passing.
  - Mutation checks (reranker weight, fallback, using the scores): each caught.
  - Fixed an F3.1 test that failed when `EMBEDDING_CACHE_DIR` was exported in the shell.
- **Docs:** README retrieval section, `.env.example`, the MVP-PLAN tech stack and F3.2 row, Decision Log, Known Issues.

### 2026-11-21: F3.1 hybrid search
- **Built** (`backend/app/retrieval/`):
  - Query embedder: bge-small via fastembed, loaded lazily under a lock, with bge's retrieval instruction prepended.
  - Year → season filter.
  - RRF fusion, a pure function with a per-article cap.
  - `HybridSearcher`: one SQL round trip for the three candidate lists, one for the chosen rows.
  - CLI `python -m app.retrieval`.
  - `EMBEDDING_CACHE_DIR` setting; docker compose mounts `data/models`.
- **Migration 0007:** `unaccent` + `apex_english` text search config; `ix_chunks_tsvector` rebuilt on it. Ingestion's full-text test updated to the new config.
- **Tuning** on 15 labelled questions (famous incidents, each naming the article that must come back), comparing candidate counts (50/100), k (20/60), caps (1/2/3), weights, AND vs OR full-text and the article list:
  - Vector only (no instruction, no cap): 14/15 in the top 10. Senna/Suzuka fails (1989 Japanese GP at #11–20).
  - Chunk all-words full-text added: the 1989 race never matches, since no chunk has all four words. Any-word (OR) full-text is noisy ("Abu Dhabi 2021" promotes every year's Abu Dhabi race).
  - Article all-words list added (first version 3.3 s; rewritten as one GIN lookup per word): 15/15 in the top 10, 13/15 in the top 5, Senna/Suzuka with both races in the top 6.
  - The season filter raised MRR from 0.746 to 0.781.
  - Production code reproduces it exactly.
- **Performance** (full corpus, local):
  - ~10 ms per warm search, embedding included; SQL 1–3 ms per list, all on indexes.
  - Peak backend memory with the model loaded: 247 MB of the 768 MB limit.
- **Tests:** backend 174 unit (+79) and 123 integration (+16), all passing; corpus 15/15 (`pytest -m corpus`); ingestion 532 passing. Mutation checks (season filter keeps untagged chunks, article list needs every word, per-article cap): each caught by its test.
- **Docker:** dev stack rebuilt and healthy, migrations at 0007, search works in the container. The runtime image builds, is healthy and runs non-root; 612 MB (was 340 MB).
- **Docs:** README knowledge-search section, `.env.example`, DATA-STRATEGY full-text row. Also fixed the README's integration-test example, which pointed `TEST_DATABASE_URL` at the real `apexgpt` database.
- Resolved the Known Issues on accent folding and filter indexes; new ones for F3.2, F3.6 and F7.1.

### 2026-11-21: Setup on a new machine and corpus rebuild
- Fresh clone with a new `.env`. The dev DB volume had been initialised with an earlier `POSTGRES_PASSWORD`, so the backend failed with "password authentication failed". Fixed by setting the role's password to the `.env` value (`ALTER ROLE`) instead of recreating the volume, which kept the loaded structured data. Postgres only reads `POSTGRES_PASSWORD` when a volume is first created.
- `data/` is git-ignored, so the Wikipedia corpus had to be rebuilt: select (2,349 articles) → fetch → clean → chunk → embed. Results match the 2026-11-17 run: 14,581 chunks, 17.7 MB of text, `chunks` table 57 MB, database 77–81 MB (size guard OK).
- Timings: the fetch took ~4¼ h (Wikipedia renders each article on request, 2–17 s each), not the ~40 min the README said; embedding took 17 min. README updated.
- User gave the go-ahead for Phase 3, starting with F3.1.

### 2026-11-17: Phase 2 closed
- PR #21 (Phase 2 close-out docs) merged.
- User decision on the open done-check item: **carry the Senna/Suzuka search criterion into Phase 3** as an acceptance test (F3.1 top results; F3.2 top 5 after reranking). **Phase 2 is complete.**
- `main` synced; working tree clean. Phase 3 not started; waiting for the user's go-ahead.

### 2026-11-17: Phase 2 wrap-up
- PR #20 (F2.6) merged: **all Phase 2 features (F2.1–F2.6) are merged.**
- Phase 2 delivers:
  - the Wikipedia pipeline: select (2,349 articles), fetch (cached), clean (17.7 MB of text), chunk (14,581 chunks), embed (bge-small, `halfvec(384)`, HNSW + full-text GIN), all incremental and offline-friendly;
  - the database size guard.
- **Done check:**
  - Chunk count and size are met.
  - The search criterion is only partly met (details in the Phase 2 checklist). Left open for the user to decide; Phase 3 hybrid search and reranking target it directly.
- Loose ends found and fixed:
  - The running dev backend container predated the `pgvector` dependency: `import pgvector` failed, and its next restart would have failed in `alembic upgrade head`. Rebuilt with `docker compose up -d --build`: healthy, migrations at head. **Anyone with an older local stack must rebuild once.**
- Loose ends checked and left as they are:
  - The dev DB's tsvector index was created before the expression was rewritten in Postgres's printed form. It is the same expression tree, so nothing to change.
  - A local `apexgpt_test` database (in the compose Postgres) is used for integration tests. The tests truncate it, so never point `TEST_DATABASE_URL` at `apexgpt`.
- Carried into Phase 3 (Known Issues): accent folding in full-text search, filter indexes, the Phase 2 search criterion.
- Phase 3 not started; waiting for the user's go-ahead.

### 2026-11-17: F2.6 size guard
- PR #19 (F2.5) merged.
- New `ingestion/common/size_guard.py`:
  - `SizeGuard(warn=700 MB, refuse=900 MB)`. `check()` raises `SizeLimitError` at or over the limit and warns past 700 MB. `report()` logs per-table rows, data, index and total sizes and the database total.
  - Standalone `python -m common.size_guard` reports and exits 1 at or over the limit.
  - Exact row counts: the planner's estimates were misleading (chunks 14,080 v 14,581; lineage 0 v 33).
- Wired in:
  - **Structured loader:** check before loading; `load(before_commit=…)` checks inside the transaction (rollback when crossed); report after. The CLI connection is now autocommit, so the size queries don't wrap `load()`'s transaction in an outer one.
  - **`narrative.embed`:** check before planning; `sync_chunks(before_batch=…)` checks before each batch; report after.
- **Real runs:**
  - structured reload: OK, report printed;
  - embed: nothing to do, report printed;
  - database **80.2 MB** in total (chunks 59.5, results 3.3, driver_standings 2.9, …).
- **Tests:** ingestion 532 (+19: thresholds, the CLI hides the URL; integration: check ok/warn/refuse, report with exact counts and size order, OVER THE LIMIT flag, a load crossing the limit rolls back everything, chunk sync stops at the limit keeping committed batches, both loader CLIs refuse and report, standalone exit codes). Backend 202, frontend 30 unchanged.
- **Mutation checks:** 5 guard hooks. The embed pre-check was initially not caught (the per-batch check refused too), so the test now asserts the stage.
- PR #20 merged 2026-11-17.

### 2026-11-16: F2.5 embedding pipeline
- PR #18 (F2.4) merged. Corrected F2.4's reported chunk count: **14,581** (14,571 was counted before the final overlap fix).
- Backend: `pgvector` 0.5.1; model `app/db/models/narrative.py` (`Chunk`) + migration **0006**: `chunks` with `halfvec(384)` + HNSW (`halfvec_cosine_ops`), GIN on `to_tsvector('english', title || ' ' || text)` (no stored tsvector), check constraints (depth, hash format, non-empty text, positive tokens, index ≥ 0), FKs to seasons/races/circuits ON DELETE SET NULL. Expression written as Postgres prints it, so the model/migration drift test stays empty.
- Ingestion: `fastembed` 0.9.1 (lock pinned to releases ≥ 2 weeks old: numpy 2.5.4, onnxruntime 1.31.1, click 8.5.0, filelock 4.2.6). New `embedder.py` (bge-small via fastembed, model cached in `data/models/`, exact truncation count from the model's tokenizer, `content_hash`), `store.py` (plan → batched upserts → delete stale → row-count check) and CLI `python -m narrative.embed` (`--dry-run`).
- Benchmarked before choosing: ~10 chunks/s single process (batch 16), ~14.5/s with fastembed's multiprocessing. Not worth the complexity for a one-off run with incremental re-runs.
- Found while testing: Postgres checks NOT NULL before `ON CONFLICT`, so "keep the stored embedding" rows can't be staged as NULL → the INSERT fills them from the stored row.
- **Real run:** 14,581 chunks embedded in 37 min (6.5/s alongside the test runs); 3 chunks exceed 512 tokens (exactly as estimated in F2.4). Re-run with no changes: 0 embedded, 0 written, ~1 s. Sizes: `chunks` 57 MB (heap 20, HNSW 16, GIN 9); local DB 76 MB in total.
- **Search check (vector only, no hybrid/rerank yet):** "Senna Prost Suzuka collision" → #1 is the 1990 Japanese GP lead; also "Prost–Senna rivalry > 1989 > Decisive clash at Suzuka" and both seasons' Japan reports in the top 8. The 1989 Japanese GP race report itself is #15 (#4 in full text for 1990). "Lauda Nurburgring fire 1976" → 1976 German GP, Lauda's 1976 Nürburgring crash section. Full text misses "Nurburgring" (no accent folding) → F3.1.
- Tests: ingestion 513 (+52: hashing, vector literal, CLI errors without leaking the URL; integration with a fake embedder: first sync + metadata, HNSW nearest neighbour, FTS on title + text using the GIN index, idempotent re-run, only changed text embedded, metadata-only updates, shifted chunks reuse vectors, stale deletes, interrupted run resumes, unknown ids refused before writing, duplicate keys, wrong dimensions, race delete keeps chunks, concurrent change detected, CLI dry run/end to end/model not loaded when nothing to embed/missing table). Backend 202 (+12: indexes, ORM round trip with cosine ordering and FTS, constraints, dimensions, downgrade to 0005). Mutation-checked 5 sync rules; the final row-count check was initially not caught → added a test. Frontend 30 unchanged.
- PR raised against `main`; awaiting review.

### 2026-11-14: F2.4 chunker
- PR #17 (F2.3) merged.
- Measured first: bge-small-en-v1.5 tokenizer (fetched to the scratchpad only, not a dependency) on the cleaned corpus → 1.28 tokens/word on average, 1.39 at p99 of 350-word windows. The plan's 400–600 tokens would be truncated by the model's 512-token input → target ~450 / max 500 estimated (1.4 tokens/word), heading included.
- New `ingestion/narrative/chunker.py`: lead alone; runs of sections under one top-level heading packed up to the target (subsection heading lines inside the text; chunk labelled with the shared heading path); longer sections split into near-equal parts at paragraphs → sentences (abbreviation/initial-aware splitter) → word windows; sentence overlap ≤ 50 tokens between parts of one section, never repeating a whole paragraph, none across sections; a short leftover is absorbed into the previous part; every chunk checked ≤ max.
- New `chunks.py` (`ChunkRecord`: pageid + index, section, text, tokens, source_url/revid, all article metadata; `heading`, `embedding_text`) and CLI `python -m narrative.chunk` (`--show TITLE`). Shared atomic JSONL read/write moved to `jsonl.py` (`articles.py` uses it too).
- Iterations from real output: balanced splits still left short tails (e.g. a 98-token "Report" part) → absorb the rest when it fits; sentences of a split paragraph were rejoined as separate paragraphs → keep each piece's joiner; no overlap after a sentence-sized piece → only skip the first sentence of whole paragraphs.
- **Result:** 14,581 chunks (full 8,063, race 5,402, lead 643, circuit 473; first reported as 14,571, counted before the last overlap fix, corrected in F2.5), estimated tokens median 307 / p90 432 / max 499; real tokens median 280, p99 453, 3 chunks over 512 (max 529). 1,070 chunks under 100 tokens (mostly intro-only articles and one-line sections left after table removal). 17.3 MB of text; ~1 s.
- Tests: ingestion 461 (sentence splitter cases, packing/labels/headings, lead isolation, balanced split + overlap, coverage in order, no cross-section overlap, long paragraph/list/word-window splits, no short leftover, heading counted in size, custom sizes, bad sizes/headings; CLI end to end with metadata, `--show`, missing file, failure writes nothing, bad lines). Mutation-checked 5 rules (overlap, leftover absorption, top-level grouping, sentence joiners, whole-paragraph overlap); the leftover test initially didn't catch its mutation → rewritten so it does. Backend 190, frontend 30 unchanged.
- PR raised against `main`; awaiting review.

### 2026-11-14: F2.3 article cleaner
- Full fetch done first (user's `WIKI_USER_AGENT`, repo URL as contact): **2,349 fetched, 0 missing, 0 errors** in 63 min; every cached page matches the manifest's page id; 426 MB in `data/wikipedia/`. PR #16 (F2.2) merged.
- Surveyed the real HTML before writing rules: top-level element/class counts across the corpus, h2 headings per depth, citation `sup` classes, what race/circuit sections hold.
- New `ingestion/narrative/cleaner.py` (lxml 6.1.3): removes tables, figures/images, styles/scripts, comments, coordinates (`geo*`), and by class: navbox, hatnote, infobox, ambox, side-box, metadata, noprint, references/reflist, reference + Inline-Template sups, flagicons, thumbs, pullquotes, … (text after a removed inline element is kept). Walks the output in order with a heading path (skipped levels handled, wrapper divs entered); paragraphs, lists ("- item"), definition lists and quotes become text blocks; text normalised (NFC, nbsp, zero-width chars, leftover markers, Wayback notes, spacing). Boilerplate sections by name + patterns (`^complete`, `results$`, `records?$`, `standings$`, `references`, works lists); table notes dropped. Depth policy: full / race (session denylist) / circuit (history + track + fatalities + URL anchor) / lead.
- New `articles.py` (`articles.jsonl` model, atomic write, validated read) and CLI `python -m narrative.clean` (`--show TITLE` prints one). Reports per-depth words, stubs < 20 words (39, all real one-line stubs) and leftover markup (none on the real corpus).
- Iterations from real output: race allowlist → denylist (it was dropping "Diffuser ban and controversy", "Death of Graham Beveridge and inquiries", "Reaction", "Track invasion"); coordinates and BOM characters in race leads; "Books"/"Publications"/"General and cited references"/"List of works" sections; parse as a fragment so bare-block HTML isn't lost (real output byte-identical after the change).
- **Result:** 2,349 articles, 2,816,320 words (~3.7M tokens), 17.7 MB: race 1.06M words, full 1.60M, circuit 96k, lead 63k.
- Tests: ingestion 448 (synthetic MediaWiki-shaped HTML: furniture + boilerplate removal, each depth, race session/narrative headings, circuit anchor, heading paths, lists/dl/quotes/wrappers, inline-removal tails, nested tables in read blocks, text normalisation, boilerplate matcher, error cases; articles file round trip/atomic/bad lines; CLI end to end, missing/stale/empty articles fail without replacing the file, `--show`, leftover-markup report). Mutation-checked: disabling table removal was initially **not** caught (the walker never reads top-level tables) → added a nested-table test that catches it. Backend 190, frontend 30 unchanged.
- PR raised against `main`; awaiting review.

### 2026-11-14: F2.2 article selection
- Fresh clone set up on the dev machine: Docker Desktop started, `uv` + `pre-commit` installed (pre-commit on Python 3.12; system Python 3.9 is too old for the black hook), deps + hooks installed, compose stack healthy, real data loaded (30/30 checks), read-only role enabled; all suites passed. PR #15 (F2.1) merged.
- New in `ingestion/narrative/`:
  - `selection.py`: rules as pure functions over entity rows. Seasons full; races `race`; circuits `circuit`; drivers full if champion / winner / podium / 30+ starts, else `lead`; constructors full if constructors' champion / winner / 5+ seasons over every row sharing the article, else `lead`; topics full (upgrading already-selected articles). URL → title: http/https en.wikipedia only, percent/Unicode decoded, fragment kept as `anchor`, non-article namespaces (e.g. a `Talk:` page for Thomas Monarch) skipped. Entries for the same article merge (ids unioned, deepest depth, conflicting single values dropped). `resolve_selection`: one batched query per 50 titles; missing/disambiguation dropped, redirects merged by page id; curated titles must resolve (topics also exactly once).
  - `entities.py`: reads seasons/races/circuits/drivers/constructors + refs; career numbers from `v_driver_career`, constructors' titles from `v_season_summary`.
  - `topics.py` + `topics.yaml`: 140 curated topics in 9 groups (rivalries, safety, controversies, iconic races, regulations, cars, concepts, people, history) with optional driver/constructor/circuit refs and a season. Validated: groups, fields, refs format, season 1950–2025, duplicate titles, safe YAML only.
  - `overrides.py` + `title_overrides.csv`: 28 curated titles for stale source URLs, keyed by kind + ref (unknown ref, or an override equal to the URL's own title, fails).
  - `manifest.py`: `data/narrative/selection.json` (versioned, atomic write, only resolved/unique articles; validated on read).
  - CLI `python -m narrative.select` (`--no-resolve` offline, `--topics`, `--overrides`, `--output`); every dropped title is logged. `python -m narrative --selection [MANIFEST]` fetches the selection.
- `wiki.py`: revision queries also request `pageprops=disambiguation`; `PageRef.disambiguation`.
- Live resolve (generic test User-Agent, no personal details; Wikimedia rate-limited it with 429 + Retry-After, which the client honoured): **2,349 articles**: full 558, race 1,085, circuit 77, lead 629 (seasons 76, races 1,149 of which 64 upgraded to full by topics, drivers 813, constructors 163, circuits 77, topics 140). 48 requests.
- **Found and fixed:** 34 source URLs no longer reach an article: 32 are now disambiguation pages (incl. notable Tony Brooks, Trevor Taylor, Jimmy Davies, Paul Goldsmith and major Jaguar, Toyota, Surtees, Epperly) and 2 are missing. Titles found from the links on those disambiguation pages and checked in one batched query → `title_overrides.csv`. 6 minor intro-only entities have no clear article and stay dropped (drivers Chuck Arnold, Dick Gibson, Geoff Lees; constructors Trevis, Hall, Turner). Also caught by the topic checks: 7 wrong titles in my first `topics.yaml` draft (dropped 6, fixed 1).
- CI: `data-checks.yml` now runs `python -m narrative.select --no-resolve` on the real data (topics + overrides refs must exist).
- Tests: ingestion 369 (URL parsing incl. namespaces/hosts/encoding, depth merge table, entry merge, notable/major rules incl. seasons over shared articles without double counting, topics upgrade + metadata, unknown refs, overrides apply/curate/redundant/unknown, resolve redirects/merge/missing/disambiguation/curated failures/one batched request, topics + overrides file validation incl. the real files, manifest round trip/atomic/refusals, both CLIs end to end with a fake MediaWiki, secrets never logged; integration: entity rows + selection from a real DB). Mutation-checked two rules. Backend 190, frontend 30 unchanged.
- PR raised against `main`; awaiting review.

### 2026-11-13: F2.1 Wikipedia fetcher
- PR #14 (Phase 1 docs) merged; Phase 2 started.
- New `ingestion/narrative/` package:
  - `wiki.py`: MediaWiki client for en.wikipedia. Serial, throttled (`WIKI_MIN_INTERVAL_SECONDS`, default 1 s), `maxlag=5` with Retry-After, 429/5xx/network retries, 20 MB response cap, validated JSON (pydantic). `current_revisions()` batches 50 titles per query and maps requested titles through `normalized` + `redirects` (loop-safe); `parse()` returns rendered HTML + revid (missing → None). Title validation mirrors MediaWiki (spaces/underscores, first-letter capitalisation, forbidden characters, 255 bytes).
  - `cache.py`: one JSON file per requested title in `data/wikipedia/` (slug + SHA-256 prefix), atomic writes, unreadable files refetched. Stores resolved title, page id, revid, URL (CC BY-SA attribution) and HTML.
  - `fetch.py` + `python -m narrative`: cached articles reused; `--refresh` refetches only changed revisions; missing pages reported, not fatal. Requires `WIKI_USER_AGENT`.
- Refactor: retry logic moved from `structured/download.py` to `common/http.py` (`open_url`), shared by both fetchers.
- Live check (generic test User-Agent, no personal details): fetched 1989/1990 Japanese GP, "Schumi" → Michael Schumacher, "Toro Rosso" → Scuderia Toro Rosso; second run served from cache; `--refresh` = 1 batched request; missing page reported.
- **Found and fixed:** a `maxlag` reply on the final retry was returned instead of raising "stayed lagged".
- Tests: ingestion 238 (fake MediaWiki routing by parameters: throttling with a fake clock, maxlag/Retry-After, HTTP retries, invalid/oversized JSON, redirects/normalisation/missing, 50-title batching, redirect loops, cache round trip/uniqueness/corruption, fetch/refresh/deleted-page logic, settings validation, CLI). No real network in tests.
- PR raised against `main`; awaiting review.

### 2026-11-13: Phase 1 closed
- PR #13 (F1.6) merged. All Phase 1 features (F1.1–F1.6) merged and the phase done check passed, so **Phase 1 is complete**.
- Phase 1 delivers: the structured F1 schema (12 tables, 1950–2025), a Jolpica dump loader (verified download, one-transaction idempotent sync), entity aliases + constructor lineage (generated names + curated seeds), four LLM-facing stats views with column docs, a read-only `apexgpt_llm_reader` role limited to those views, and 30 sanity checks run before every load commit and weekly in CI against the real dump. Structured data: 11.5 MB.
- Carried into later phases (see Known Issues): the F3.5 SQL tool must validate queries (role defaults are only a backstop); F7.2 must confirm the role setup on Neon.
- Phase 2 not started yet; waiting for the user's go-ahead.

### 2026-11-13: F1.6 structured data checks
- PR #12 (F1.5) merged.
- `ingestion/structured/checks.py`: 30 checks (SQL → one value vs expected; `=`, `<`, `>=`):
  - **Facts:** the plan's three (Hamilton 105 wins, 2021 champion Verstappen, 1950 = 7 races) plus careers (Hamilton titles/poles/podiums, Schumacher wins/titles/1,566 pts, Senna 65 poles/41 wins, Prost 51, Fangio 5 titles), seasons (1950 Farina, 2008 margin 1, 2021 395.5 pts, 2025 Norris, Vanwall first constructors' champion, 2024 McLaren, 1,149 races, 24 in 2025), Senna v Prost 1988 qualifying 14-2.
  - **Integrity:** every race has results, a winner and driver standings; rounds run 1..n; every season has a champion; every season from 1958 a constructors' champion; every driver has an alias.
  - **Size:** F1 tables < 25 MB.
- A check runs only when every season it covers is loaded (partial loads skip old facts); alias checks skip with `--no-seeds`.
- The loader runs them **inside its transaction before commit**: a failure raises `DataCheckError` and rolls back everything. New `--no-checks` flag. Standalone read-only runner: `python -m structured.checks`.
- Real data on the dev DB: **30/30 pass; 11.5 MB**. An injected wrong expectation (106 wins) stopped the load with exit 1.
- New workflow `data-checks.yml`: fresh Postgres → migrations → real load (checks in-transaction) → standalone checks → second load must change nothing. Runs on PRs/pushes touching ingestion/schema, weekly (Mon 06:00 UTC), on demand; dump cached by ISO week; not part of the `CI passed` gate.
- Fixed while testing: the standalone runner used `run_checks`' default argument (bound when defined); it now passes `CHECKS` explicitly.
- Tests: ingestion 192 (applicability, describe/error text, the real check list's definitions, size check covers all tables, every real check's SQL runs against the schema with the right type, integrity checks pass on consistent data, pass → commit, fail → full rollback, checks see uncommitted data, loader CLI fails/rolls back then succeeds with `--no-checks`, standalone CLI). Backend 190 unchanged.
- **Phase 1 done check passed** (pending this PR's merge).
- PR raised against `main`; awaiting review.

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

- F6: gpt-oss sometimes answers a narrative question with the stats tool only (live: 2 of 9 runs of "Explain Abu Dhabi 2021" during F4.4: two `query_stats` calls, no knowledge search, so no citations). The F4.1 live test fails when it happens. Tune the tool descriptions/prompt against the golden set. **Update (F5.2):** some "no citations" answers were a backend bug, not the model: gpt-oss wrote markers as `[\u200bS1\u200b]` (zero-width spaces), which the citation filter didn't recognise, so the sources were dropped even though the knowledge search ran. Fixed; the stats-only case remains.
- F5.4: two tabs with the **same** chat open: each tab's save replaces that chat with its own copy (last write wins); other chats are safe. A deleted chat still open in another tab comes back if that tab saves it. Fine for a no-login MVP.
- F4.4: the answer cache is per process and isn't cleared by a data reload; reloaded data shows once entries expire (24 h) or on restart. Fine while the data covers finished seasons.
- F7.1: the rate limits key on the client address, so `FORWARDED_ALLOW_IPS` must be the proxy's address in production, or every visitor shares the proxy's limit.
- F7.3: add `python -m app.feedback purge` to the weekly scheduled workflow (with the backup), so feedback expires after 90 days even when none is submitted. Until then, rows are purged whenever new feedback is saved.
- F3.5/F6: the stats views can't answer per-season poles (`v_driver_career` has career totals, `v_race_winners` only winners). Found in the F4.2 check: "How many poles did Ayrton Senna take in 1988?" answered 7 (the wins from pole; the data has 13). Add per-season driver stats (wins, poles, podiums, points) to the views, or a season-results view, and a golden-set question for it.
- F4.2: the condense rewrite may add a name the conversation didn't contain (live: "the race director" → "Michael Masi"). Helpful for retrieval, and the answer stays grounded in the tools, but it can steer the answer wrong; score it on the golden set (F6). Requests that aren't questions ("shorter please", "as a table") are condensed like questions; the answering model never sees the earlier answer.

- F6: the reranker settings (MiniLM-L-6, blend ×2, 10 candidates) were chosen on 15 questions. Re-check them on the ~100-question golden set; the corpus tests are the regression guard until then. "How did Hunt beat Lauda in 1976" is the closest call (rivalry lead at #5).
- F3.6: words like "explain" or "tell me about" count for the text and article lists (all words must match). Vector search covers these questions today; the knowledge tool can pass the LLM's search terms instead of the raw question.
- F4.4/F7.1: one answer holds a worker thread for its whole stream (~2–8 s); the single uvicorn worker's thread pool (40) bounds concurrent answers. Fine at MVP traffic; the F6.4 load test should confirm.
- F7.1: mount a volume at `/app/logs` in production (and set `LOG_FILE`), or logs are lost on every deploy. Logs hold questions; rotation bounds them by size (10 MB × 5), not by age. If a time limit is wanted (like feedback's 90 days), add a time-based rotation.
- F6: fallback answers (Gemini lite, nemotron) are less polished than gpt-oss-120b's; the golden set should score each provider. Gemini 3.x flash previews and newer flash models were overloaded when tested; revisit the default.
- F3.7/F6: the `query_stats` description is ~1,000 tokens and goes with every request that offers the tool. On Groq's free tier, 8 quick text-to-SQL requests hit the per-minute token limit (429); with no Gemini/OpenRouter key there is no fallback. The orchestrator should offer tools only when needed and keep prompts small; adding the fallback keys helps.
- F3.4: an everyday-word surname in an all-lowercase question isn't found ("pace" for Carlos Pace); write it capitalised or use the full name. When new drivers or teams are loaded, check whether any new single-word alias is an everyday word and add it to `COMMON_WORDS` in `app/retrieval/entities.py`.
- F3.4: candidates are ordered, not decided. The orchestrator (F3.7) should use the best guess, but mention the alternatives when `ambiguous` and no season settles it (e.g. "Schumacher" alone).
- F3.3: the Gemini (`gemini-2.5-flash`) and OpenRouter (`openai/gpt-oss-120b:free`) default models are unverified (no keys yet). A wrong model fails with 404 and falls through, so check with `LLM_LIVE_TESTS=1 uv run pytest -m llm` once keys are added.
- F7.1: production needs `GROQ_API_KEY` (and the fallback keys) set as Coolify secrets; docker compose already passes them to the backend.
- F7.1: the backend runtime image grew from 340 MB to 612 MB with fastembed/onnxruntime (F3.2's reranker added no dependencies). In production both models (~145 MB) download to a temporary directory on first search: bake them into the image or mount a volume. Set `ONNX_THREADS` to the production CPU limit.
- F2.5: fastembed downloads the model from Hugging Face without a token (a rate-limit warning is printed; harmless).
- F2.4/F2.5: 4 chunks are longer than bge-small's 512-token limit, so their ends are not embedded (they are still in full-text search). Check whether the chunker's token count matches the model's tokenizer; revisit in F6 tuning.
- F2.3: 39 cleaned articles are under 20 words (very short Wikipedia stubs, e.g. "Al Herman"). Kept; check whether intro-only entities need fuller coverage in F6.

- Set `FORWARDED_ALLOW_IPS` to the Coolify/Traefik proxy network (never `*`). To do in F7.1.
- F7.2 (Neon): confirm the migration's `CREATE ROLE` works as the Neon owner role and run `python -m app.db.readonly_role` against Neon.
