# ApexGPT

A Formula 1 chat assistant. Ask about drivers, constructors, circuits, seasons, races, crashes, rivalries and championship battles from **1950 to 2025**, and get grounded answers with sources.

ApexGPT uses a hybrid RAG design: statistical questions are answered with SQL over structured F1 data, and narrative questions with vector search over curated F1 articles. It runs entirely on free models and services.

> **Status:** in development (MVP). See [docs/PROGRESS.md](docs/PROGRESS.md).

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI |
| Frontend | Next.js (TypeScript, Tailwind) |
| Database | Postgres + pgvector (Neon in production, Docker locally) |
| Embeddings / reranking | fastembed (`bge-small-en-v1.5`, `bge-reranker-base`) |
| LLM | Free tiers via the openai SDK (OpenAI-compatible APIs): Groq → Gemini → OpenRouter |
| Data | Jolpica-F1 (structured), Wikipedia (narrative, CC BY-SA) |
| Infra | Docker, Docker Compose, Coolify |

## Repository Layout

```
backend/     FastAPI app (API, retrieval, LLM, tools)
ingestion/   Offline data pipelines (Jolpica, Wikipedia → pgvector)
frontend/    Next.js app
eval/        Golden question set and evaluation runner
docs/        Plans, data strategy and progress tracker
data/        Raw downloads (git-ignored)
```

Directories are added as their features land (see the plan).

## Getting Started

### Prerequisites

- Docker + Docker Compose
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- [pre-commit](https://pre-commit.com/) (`uv tool install pre-commit`)

### Setup

```bash
git clone https://github.com/RChaubey16/apexgpt.git
cd apexgpt
cp .env.example .env        # then fill in values
(cd frontend && npm ci)     # frontend pre-commit hooks use its pinned tools
pre-commit install
```

### Run everything with Docker Compose

```bash
docker compose up --build        # db + backend + frontend, with hot reload
```

| Service | URL (localhost only) | Notes |
|---|---|---|
| Frontend | http://localhost:3000 | `next dev`; edits in `frontend/src` reload |
| Backend | http://localhost:8000 (`/docs`, `/health`, `/health/ready`) | Runs `alembic upgrade head` on start; edits in `backend/app` reload |
| Database | `127.0.0.1:${POSTGRES_PORT}` | Postgres 18 + pgvector; data kept in the `apexgpt_pgdata` volume |

- Ports come from `.env` (`FRONTEND_PORT`, `BACKEND_PORT`, `POSTGRES_PORT`). If you change `FRONTEND_PORT`, also update `CORS_ORIGINS`; if you change `BACKEND_PORT`, also update `NEXT_PUBLIC_API_URL`.
- The backend container uses `COMPOSE_DATABASE_URL` (host `db`); `DATABASE_URL` is for running the backend on the host.
- Each service has a memory/CPU limit that mirrors the VPS budget (`docker stats` to watch).
- Run backend tests inside the stack: `docker compose exec backend pytest`.
- `docker compose down` stops everything and keeps data; `down -v` also deletes the database volume.

Or run services individually, as below.

### Database

Local Postgres 18 + pgvector 0.8.1 (matches Neon's default):

```bash
docker compose up -d db                  # bound to 127.0.0.1:${POSTGRES_PORT} only
cd backend && uv run alembic upgrade head
```

### Load F1 data (1950–2025)

The structured data (results, qualifying, standings, pit stops, …) comes from the [Jolpica-F1](https://github.com/jolpica/jolpica-f1) CSV database dump: free, delayed 14 days, for non-commercial use.

```bash
cd backend && uv run alembic upgrade head && cd ..   # schema first
cd ingestion
uv sync
uv run python -m structured              # download (cached in data/jolpica/), verify SHA-256, load
uv run python -m structured --dry-run    # transform only and print row counts; no DB needed
uv run python -m structured --help       # --dump <zip>, --first-season, --last-season, --no-seeds, --no-checks
uv run python -m structured.checks       # run the sanity checks read-only against DATABASE_URL
uv run pytest                            # unit tests; integration tests need TEST_DATABASE_URL
```

- Uses `DATABASE_URL` from `.env`. Takes ~10 s; the result is ~13 MB.
- The load is one transaction: re-running is safe (unchanged rows aren't touched) and a failure leaves the database as it was. Races in the loaded season range that disappear from the dump are deleted; other seasons are never touched.
- Bad source data (missing columns, unparseable values, broken references) stops the load with a message naming the table, row and column.
- **Sanity checks** ([`ingestion/structured/checks.py`](ingestion/structured/checks.py)) run inside the load transaction, before commit: known facts (Hamilton 105 wins, 2021 champion, 1950 = 7 races, …), integrity rules (every race has a winner, every season a champion, …) and the 25 MB size budget. If one fails, the load is rolled back, so a bad dump never replaces good data. Checks only run when all the seasons they cover are loaded.
- **Aliases and team lineage** are synced in the same transaction. Drivers' full names/surnames and constructors' names are generated; nicknames ("Schumi", "Checo", "Silver Arrows") and team successions (Tyrrell → BAR → Honda → Brawn → Mercedes) are curated in [`ingestion/structured/seeds/`](ingestion/structured/seeds/). Seeds use driver/constructor `ref` slugs. Edit a CSV and re-run the loader to apply it; lineage rows are checked against the race data (the successor raced in that season, the predecessor in that season or the one before).

### Choose and fetch Wikipedia articles

The narrative corpus (Phase 2) starts from Wikipedia articles fetched through the MediaWiki API and cached in `data/wikipedia/` (git-ignored). Set `WIKI_USER_AGENT` in `.env` first: Wikimedia asks for a client name and contact details. The structured data must be loaded (the selection is computed from it).

```bash
cd ingestion
uv run python -m narrative.select --no-resolve   # offline: build the selection, print counts
uv run python -m narrative.select                # resolve on Wikipedia (~50 requests), write data/narrative/selection.json
uv run python -m narrative --selection           # fetch every selected article (~2,400 requests, ~4 h; resumable)
uv run python -m narrative --selection --refresh # later: refetch only articles whose revision changed
uv run python -m narrative.clean                 # clean all of them -> data/narrative/articles.jsonl (~2 min, offline)
uv run python -m narrative.clean --show "1990 Japanese Grand Prix"   # inspect one cleaned article
uv run python -m narrative.chunk                 # split into chunks -> data/narrative/chunks.jsonl (seconds, offline)
uv run python -m narrative.chunk --show "1990 Japanese Grand Prix"   # inspect one article's chunks
uv run python -m narrative.embed --dry-run       # what would be embedded / written / deleted (no model, no writes)
uv run python -m narrative.embed                 # embed new or changed chunks, sync the chunks table (~15–25 min the first time)

uv run python -m narrative --title "1989 Japanese Grand Prix" --title "Ayrton Senna"   # ad hoc
uv run python -m narrative --titles-file titles.txt             # one title per line, # comments
```

- The full fetch is slow because Wikipedia renders each article on request (2–17 s each). Requests stay serial on purpose (Wikimedia's API etiquette), so don't parallelise it. On macOS, `caffeinate -i -w <pid>` keeps the machine awake until the fetch exits.
- `data/` is git-ignored, so a fresh clone has no corpus. Copy `data/wikipedia/` from another machine to skip the fetch, or run the whole sequence above (about 4½ hours end to end).

**Selection** ([`ingestion/narrative/selection.py`](ingestion/narrative/selection.py)) follows `docs/DATA-STRATEGY.md` §2b. Titles come from each entity's Wikipedia URL in the structured data, never guessed:

| Articles | Depth |
|---|---|
| Season articles | full |
| Grand Prix race reports | `race`: lead + background + race report |
| Notable drivers (champion, race winner, podium, or 30+ starts) | full |
| Other drivers | `lead`: intro only |
| Major constructors (constructors' champion, race winner, or 5+ seasons) | full |
| Minor constructors | `lead` |
| Circuits | `circuit`: lead + history |
| Curated topics ([`narrative/topics.yaml`](ingestion/narrative/topics.yaml)) | full |

- Constructor rows sharing an article (Cooper-Climax, Cooper-Maserati → Cooper Car Company) become one entry; the major rule is applied over all of them.
- A topic naming an already-selected article (a race report, a driver) upgrades it to full text and tags it with the topic group.
- Resolving drops missing and disambiguation pages and merges titles that redirect to the same page. A topic that's missing, a disambiguation page or a duplicate fails the run (it's a mistake in `topics.yaml`). Unknown refs in `topics.yaml` fail even with `--no-resolve`.
- Each manifest entry keeps the metadata its chunks will carry: kinds, depth, `season`, `race_id`, `circuit_id`, `driver_ids`, `constructor_ids`, `topic`, plus a URL `anchor` hint (e.g. `Las Vegas Grand Prix#Circuit`).

**Fetching:**

- Requests are serial and throttled (`WIKI_MIN_INTERVAL_SECONDS`, default 1 s), send `maxlag=5`, and retry 429/5xx/lag with backoff.
- Redirects and title normalisation are followed ("Schumi" → Michael Schumacher). Pages that don't exist are reported, not treated as errors.
- Each cached article keeps its resolved title, revision id and URL (needed for CC BY-SA attribution). Cached articles are never refetched unless `--refresh` finds a newer revision (checked 50 titles per request).

**Cleaning** ([`ingestion/narrative/cleaner.py`](ingestion/narrative/cleaner.py)) follows `docs/DATA-STRATEGY.md` §2a:

- Removes all tables (results, standings, infoboxes, navboxes, succession and maintenance boxes), images and captions, hatnotes, reference lists, coordinates, inline styles and citation markers.
- Drops boilerplate sections (References, Notes, See also, External links, Racing record, Helmet, book lists) and every results/records/classification/standings section, plus the table notes they leave ("Source: …").
- Then applies the article's depth: `full` keeps every section; `race` keeps everything but practice/qualifying/sprint/entry-list sections (so "Background", "Race", "Aftermath", "Diffuser ban and controversy" all stay); `circuit` keeps history, layout and fatal-accident sections (+ the URL's `#anchor` section); `lead` keeps the intro.
- Output: `data/narrative/articles.jsonl`, one article per line with the selection metadata, page/revision/URL (for attribution) and its sections as heading paths + paragraphs. Never replaced by a partial run: missing or stale cached articles fail it. Stubs (< 20 words) and any leftover markup are reported.
- Full corpus: 426 MB HTML → 17.7 MB clean text, ~2.8M words (~3.7M tokens).

**Chunking** ([`ingestion/narrative/chunker.py`](ingestion/narrative/chunker.py)) follows `docs/DATA-STRATEGY.md` §2c:

- Splits on section boundaries: the lead is its own chunk, and a chunk never mixes two top-level sections. Small subsections of one top-level section are packed together, each under its own heading line.
- A longer section is split into near-equal parts at paragraphs (then sentences, then words, only if one is too long); consecutive parts of a section overlap by the last sentence or two (≤ ~50 tokens), never across sections.
- Sized for the embedding model (bge-small, 512-token input): target ~450 / max 500 estimated tokens *including* the `title > section` heading the chunk is embedded with. Estimates use 1.4 tokens per word (measured with the bge-small tokenizer on this corpus: mean 1.28, p99 1.39).
- Output: `data/narrative/chunks.jsonl`, one chunk per line: `pageid` + `index` (unique), `section` heading path, `text`, estimated `tokens`, `source_url`/`revid` (attribution) and the article's `season`, `race_id`, `circuit_id`, `driver_ids`, `constructor_ids`, `topic`, `depth`, `kinds` for filtering.
- Full corpus: **14,581 chunks**, median ~307 estimated tokens (~280 real), 17.3 MB of text.

**Embedding** ([`ingestion/narrative/embed.py`](ingestion/narrative/embed.py)) loads the chunks into the `chunks` table (backend migration 0006):

- Model: `BAAI/bge-small-en-v1.5` via fastembed (ONNX, CPU), 384 dimensions, stored as `halfvec(384)` with an HNSW cosine index. Downloaded once (~65 MB) into `data/models/`. The backend must embed questions with the same model (`query_embed`).
- Full-text search: a GIN index on `to_tsvector('english', title || ' ' || text)`. There's no stored tsvector column, so queries must use the same expression.
- Incremental: each row stores a hash of model + embedded text. Unchanged chunks are not re-embedded, and chunks that only moved (an article gained a section) reuse their stored vector. Metadata-only changes are written without embedding.
- Safe to interrupt: writes are committed in batches of 256, and a re-run picks up where it stopped. Chunks no longer in the file are deleted last. Ids missing from the structured data are refused before anything is written.
- Full corpus: 14,581 chunks embedded in ~37 min (~6.5 chunks/s on a laptop CPU); the table is ~57 MB (heap 20 MB, HNSW 16 MB, GIN 9 MB). A re-run with nothing changed takes about a second.

### Database size guard

Production runs on Neon's free tier (1 GB per project), so the loaders guard the budget (`docs/DATA-STRATEGY.md` §4, [`ingestion/common/size_guard.py`](ingestion/common/size_guard.py)):

- **Refuses at 900 MB**, checked before every load:
  - The structured loader checks again just before commit, so a load that crosses the limit rolls back.
  - `narrative.embed` checks again before every batch, so it stops at the limit and keeps the batches already committed.
- **Warns at 700 MB.**
- After each run, prints every table's rows, data, index and total size, plus the database total.
- Report only: `cd ingestion && uv run python -m common.size_guard`. It exits 1 at or over the limit; use it against Neon after a restore.
- Current local size: **80 MB** (chunks 60 MB, structured data ~11 MB).

### Stats views

Migration `0004` adds four read-only views that the LLM's SQL tool will query (F3.5). Each has `COMMENT ON` text explaining its columns and the data's limits (`\d+ v_driver_career` in psql):

| View | One row per |
|---|---|
| `v_race_winners` | race win (season, race, circuit, driver, team, race time, Wikipedia URL) |
| `v_driver_career` | driver: entries, starts, wins, podiums, poles, fastest laps (2004+), DNFs, titles, points, teams |
| `v_season_summary` | season: champion, runner-up, title margin, constructors' champion, distinct winners |
| `v_head_to_head_teammates` | season × team × driver × teammate (both directions): qualifying, finishing, wins, points |

The LLM's queries run as **`apexgpt_llm_reader`** (migration `0005`): it can only `SELECT` these four views (no table access, no writes or DDL), with a 5 s statement timeout, read-only transactions and at most 5 connections. Migrations create it without a password; set one in `READONLY_DATABASE_URL` (`.env`), then enable login:

```bash
cd backend && uv run python -m app.db.readonly_role   # sets the password, enables LOGIN, checks a view is readable
```

Re-run it to rotate the password.

Poles use `grid = 1` (qualifying data starts in 1994), fastest laps are only recorded from 2004, and starts are approximate (see `docs/DATA-STRATEGY.md`).

### Stats tool

`query_stats`, the tool through which the LLM answers statistics questions ([`backend/app/tools/`](backend/app/tools/)). The LLM writes one SQL `SELECT` over the stats views; the tool checks it, runs it as the read-only role and returns the rows. It needs `READONLY_DATABASE_URL` (and `COMPOSE_READONLY_DATABASE_URL` for docker compose) with the role's login enabled (see Stats views).

```bash
cd backend
uv run python -m app.tools.stats --schema                   # the views and column notes the LLM sees
uv run python -m app.tools.stats "SELECT driver_name, wins FROM v_driver_career ORDER BY wins DESC LIMIT 5"
uv run python -m app.tools.stats "SELECT * FROM drivers"    # rejected: unknown table drivers (exit 2)
```

- **Validation** ([`sql_guard.py`](backend/app/tools/sql_guard.py)): the SQL is parsed with Postgres's own parser (`pglast`, Postgres 18 grammar), and the whole tree must pass allowlists:
  - one `SELECT` (WITH/UNION allowed) reading only the four views (or its own CTEs);
  - known-safe node types only, which rules out `INTO`, `FOR UPDATE`, data-modifying CTEs, `$1` parameters, functions in `FROM` and `TABLESAMPLE`;
  - allowlisted functions and cast types only, which keeps out `set_config`, `pg_sleep`, `query_to_xml`, file readers and `::regclass`.
- **What runs** is the SQL *regenerated from the validated tree*, with `LIMIT` capped at 51, so exactly what was checked executes. At most 50 rows come back, and a note says when more existed.
- **Then the database:** each query runs as `apexgpt_llm_reader` in a `READ ONLY` transaction, with the tool's own `statement_timeout` (3 s) and `lock_timeout` (1 s).
- **Errors are written for the LLM to fix its query:** why a query was rejected, or Postgres's one-line message (`column "x" does not exist`, `division by zero`, a timeout). Connection details never appear.
- **The tool description** (`tool_definition(tool.schema())`) lists every view, column and `COMMENT ON` note (~4,000 characters). It also tells the model never to answer a "most / best" question with `LIMIT 1`, because records are often shared (Monza: Hamilton and Schumacher, 5 wins each).
- `LLM_LIVE_TESTS=1 uv run pytest -m llm` also runs 5 questions end to end: the real LLM writes the SQL and the tool answers.

### Knowledge search

Retrieval over the Wikipedia chunks ([`backend/app/retrieval/`](backend/app/retrieval/)): hybrid search, then reranking, then the top 5 (`build_retriever(settings).retrieve(session, question)`). It needs the corpus loaded (above) and migrations at head.

```bash
cd backend
uv run python -m app.retrieval "Senna Prost Suzuka collision"     # top 5, reranked, with the lists that found each
uv run python -m app.retrieval "Lauda 1976" --limit 10 --show-text
uv run python -m app.retrieval "Lauda 1976" --no-rerank           # hybrid order only, to compare
uv run python -m app.retrieval "Lauda crash" --season 1976        # explicit season filter
uv run python -m app.retrieval "Lauda 1976" --no-filters          # ignore the year in the question
```

- **Hybrid search: three ranked lists, fused with Reciprocal Rank Fusion** (weights 1.0 / 0.5 / 0.5, 50 candidates each, at most 2 chunks per article):
  - **vector:** nearest chunks to the question's bge-small embedding (HNSW).
  - **text:** chunks containing every word of the question (full-text, GIN).
  - **article:** articles containing every word somewhere, each represented by its chunk nearest to the question. Race articles rarely repeat the circuit or the drivers in every section.
- **Accents are folded** in full-text search: "Nurburgring" matches "Nürburgring", "Raikkonen" matches "Räikkönen". This uses the `apex_english` text search configuration, which is `unaccent` plus English stemming (migration 0007).
- **Years in the question filter by season** (1950–2025). The filter keeps that season's chunks and every chunk without a season, such as driver, team and topic articles. A decade ("the 1980s"), a year after 2025, or more than 10 years means no filter.
- **Reranking (F3.2):** the hybrid search's 10 best chunks are scored by a cross-encoder, `Xenova/ms-marco-MiniLM-L-6-v2`. Its order is blended with the hybrid order (RRF, reranker ×2) and the best 5 are kept. If the reranker fails, the hybrid order is used and a warning is logged. The plan's `bge-reranker-base` was measured and rejected; see the Decision Log in `docs/PROGRESS.md`.
- **Models:** the query embedder (`BAAI/bge-small-en-v1.5`, ~65 MB) and the reranker (~80 MB) download on first use into `EMBEDDING_CACHE_DIR`; docker compose mounts `data/models` for them.
- **Threads:** each model uses `ONNX_THREADS` threads (default 1). Keep that at the backend's CPU limit. ONNX Runtime otherwise starts one thread per host core: in the 1-CPU dev container that made retrieval 16 s instead of 0.7 s.
- **Cost:** on the full corpus in the dev container (1 CPU), one retrieval takes ~0.7 s warm: ~0.1 s for the hybrid search, ~70 ms per reranked chunk. With both models loaded the backend uses ~400 MB of its 768 MB limit.
- Errors: bad input raises `ValueError`. A database or embedding-model failure raises `SearchError` with a message that is safe to show users; logs record only the error class.

### Entity resolution

Finds the drivers, constructors and circuits named in a question ([`backend/app/retrieval/entities.py`](backend/app/retrieval/entities.py)), so later tools can work with IDs instead of names.

```bash
cd backend
uv run python -m app.retrieval.entities "Did Schumi beat Hill at Adelaide in 1994?"
# "Schumi" -> Michael Schumacher · "Hill" (ambiguous) -> Damon Hill first (raced in 1994), Graham, Phil · "Adelaide" -> Adelaide Street Circuit
```

- **Names:**
  - Drivers and constructors come from the alias tables: full names, surnames, constructor names and curated nicknames ("Schumi", "the Professor", "Checo").
  - Circuits come from the `circuits` table (ref, locality, and the name without generic words, e.g. "Circuit de Spa-Francorchamps" → "spa francorchamps"), plus a few curated names ("Singapore", "COTA", "Nordschleife").
  - Questions are normalised like the alias tables, so accents and case don't matter.
- **Matching:**
  - The longest alias wins ("Red Bull Ring" is the circuit, not the team).
  - Single-word aliases that are everyday words ("pace", "speed", "era", "driver") count only when capitalised.
  - "March" and "May" never count alone.
- **Ambiguity is kept.** Each mention lists up to 5 candidates, best first:
  1. active in a season the question names;
  2. match strength: full name > nickname > team name = surname > circuit;
  3. wins, then races.

  So "McLaren" is the team and "Prost" is Alain Prost.
- The index (~2,000 aliases) loads on first use (~40 ms) and is reloaded every 6 hours; a question resolves in ~20 µs. If a reload fails, the previous index is kept.

### LLM client

Free-tier LLMs with fallback ([`backend/app/llm/`](backend/app/llm/)): `build_llm_client(settings).complete(messages, tools=...)` for answers and tool calls, and `.stream(messages)` for streamed text. Set at least `GROQ_API_KEY` in `.env`.

```bash
cd backend
uv run python -m app.llm "Who won the 1976 championship?"   # shows which provider answered
uv run python -m app.llm "Explain DRS" --stream
uv run python -m app.llm "Hi" --provider gemini             # only this provider
LLM_LIVE_TESTS=1 uv run pytest -m llm                       # each configured provider: answer, tool call, stream
```

- **Providers:** Groq → Gemini → OpenRouter, through their OpenAI-compatible APIs with the official `openai` SDK. Only providers with a key are used. Models are settings (`LLM_GROQ_MODEL`, …), because free-tier lists change; the Groq default is `openai/gpt-oss-120b`.
- **Fallback:**
  - A timeout, connection error or 5xx is retried on the same provider (`LLM_MAX_RETRIES`, default 1), then the next provider is tried.
  - A rate limit (429), bad key, retired model (404) or rejected request (400) moves straight to the next provider.
  - A response it can't use (empty, a tool that wasn't offered, arguments that aren't a JSON object) is treated as a failure too.
- **Streaming** falls back the same way until the first token. After that, a failure raises `LLMStreamInterruptedError`, because part of the answer has already been shown.
- **Errors:** bad requests raise `ValueError` before any call. When every provider fails, `LLMUnavailableError` is raised with a message that is safe to show. Logs carry the provider, model, error class and status code, never prompts, answers or keys.

### Backend

```bash
cd backend
uv sync                                  # install dependencies (incl. dev)
uv run uvicorn app.main:create_app --factory --reload   # http://localhost:8000/health, docs at /docs
uv run pytest                            # unit tests (no database needed)

# Integration tests: real DB. They migrate down to an empty schema, so use the
# separate test database, never one with real data.
TEST_DATABASE_URL=postgresql://apexgpt:change-me@localhost:5432/apexgpt_test \
  uv run pytest -m integration

# Search quality on the loaded corpus (read-only; the F3.1/F3.2 acceptance tests).
CORPUS_DATABASE_URL=postgresql://apexgpt:change-me@localhost:5432/apexgpt \
EMBEDDING_CACHE_DIR=../data/models uv run pytest -m corpus
```

Health endpoints: `/health` is liveness only and never touches the DB, so the 30s Docker healthcheck doesn't keep Neon awake. `/health/ready` checks the DB and returns 503 if it's unreachable.

Docker image (production target):

```bash
docker build -t apexgpt-backend backend/
docker run -p 8000:8000 -e DATABASE_URL=postgresql://... apexgpt-backend
```

### Frontend

```bash
cd frontend
npm ci
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
npm run dev                              # http://localhost:3000
npm test && npm run lint && npm run typecheck
```

`NEXT_PUBLIC_API_URL` is inlined at **build time**, so the Docker image takes it as a build arg. Details: [frontend/README.md](frontend/README.md).

## Development Workflow

- One feature at a time on a `feature/<name>` branch created from `main`.
- Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`, `security:`).
- Every feature goes through a PR against `main`, reviewed before merge.
- Lint and tests must pass before a feature is committed.

### CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs on every PR to `main` and every push to `main`:

| Job | What it checks |
|---|---|
| Lint (pre-commit) | All pre-commit hooks on all files: hygiene, ruff, black, prettier, eslint, actionlint |
| Backend tests | `pytest` unit + integration tests against a Postgres 18 + pgvector service; fails if the integration tests are skipped |
| Ingestion tests | Same for `ingestion/` (the schema comes from the backend's migrations) |
| Frontend typecheck + tests | `npm run typecheck`, `npm test` |
| Docker runtime images | Builds the production images, starts them, waits for `HEALTHCHECK` to report healthy, checks they run as non-root |
| Docker compose stack | `docker compose up --wait` with `.env.example`, then checks `/health`, `/health/ready` (DB + migrations), the frontend and CORS |
| CI passed | Passes only if every job above passed; this is the single check to require in branch protection |

A second workflow, [`.github/workflows/data-checks.yml`](.github/workflows/data-checks.yml), loads the **real** Jolpica dump into a fresh database and runs the sanity checks, then reloads to prove nothing changes. It runs on PRs/pushes that touch `ingestion/` or the schema, weekly, and on demand. It's kept out of the `CI passed` gate so a Jolpica outage can't block unrelated PRs; the dump is cached between runs.

To run the lint job locally: `pre-commit run --all-files`.

Details: [docs/MVP-PLAN.md §5](docs/MVP-PLAN.md#5-development-workflow).

## Documentation

- [MVP plan](docs/MVP-PLAN.md): phases, workflow, feature breakdown
- [Feature plan](docs/FEATURES.md): all features by tier
- [Data strategy](docs/DATA-STRATEGY.md): what data is stored and why
- [Progress](docs/PROGRESS.md): current status (start here when resuming)

## Data Attribution

Narrative content is derived from [Wikipedia](https://www.wikipedia.org/) articles, licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Structured data comes from the [Jolpica-F1 API](https://github.com/jolpica/jolpica-f1).
