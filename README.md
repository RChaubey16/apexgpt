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
| LLM | Free tiers via LiteLLM: Groq → Gemini → OpenRouter |
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

### Fetch Wikipedia articles

The narrative corpus (Phase 2) starts from Wikipedia articles fetched through the MediaWiki API and cached in `data/wikipedia/` (git-ignored). Set `WIKI_USER_AGENT` in `.env` first: Wikimedia asks for a client name and contact details.

```bash
cd ingestion
uv run python -m narrative --title "1989 Japanese Grand Prix" --title "Ayrton Senna"
uv run python -m narrative --titles-file titles.txt             # one title per line, # comments
uv run python -m narrative --titles-file titles.txt --refresh   # refetch only changed revisions
```

- Requests are serial and throttled (`WIKI_MIN_INTERVAL_SECONDS`, default 1 s), send `maxlag=5`, and retry 429/5xx/lag with backoff.
- Redirects and title normalisation are followed ("Schumi" → Michael Schumacher). Pages that don't exist are reported, not treated as errors.
- Each cached article keeps its resolved title, revision id and URL (needed for CC BY-SA attribution). `--refresh` checks revisions 50 titles per request.
- Which articles to fetch is decided in F2.2; cleaning happens in F2.3.

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

### Backend

```bash
cd backend
uv sync                                  # install dependencies (incl. dev)
uv run uvicorn app.main:create_app --factory --reload   # http://localhost:8000/health, docs at /docs
uv run pytest                            # unit tests (no database needed)

# Integration tests: real DB. They migrate up/down, so never use a DB with real data.
TEST_DATABASE_URL=postgresql://apexgpt:change-me@localhost:5432/apexgpt \
  uv run pytest -m integration
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
