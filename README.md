# ApexGPT

A Formula 1 chat assistant. Ask about drivers, teams, circuits, seasons, races, crashes, rivalries and title battles from **1950 to 2025**, and get answers grounded in real data, with sources.

> **Status:** MVP in development. See [docs/PROGRESS.md](docs/PROGRESS.md).

## How it works

ApexGPT uses hybrid retrieval-augmented generation (RAG):

- **Stats questions** ("Who has the most wins at Monza?") are answered with SQL over structured race data from 1950 to 2025.
- **Story questions** ("Explain Abu Dhabi 2021") are answered from curated Wikipedia articles, using vector and full-text search plus a reranker.
- An LLM decides which of the two to use, then writes the answer and cites its sources.

It runs entirely on free models and free-tier services.

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | Next.js, React, TypeScript, Tailwind CSS |
| Backend | Python, FastAPI, SQLAlchemy, Alembic |
| Database | Postgres + pgvector (Docker locally, Neon in production) |
| Embeddings & reranking | fastembed (ONNX, CPU) |
| LLMs | Free tiers of Groq, Gemini and OpenRouter, through their OpenAI-compatible APIs, falling back in that order |
| Data | [Jolpica-F1](https://github.com/jolpica/jolpica-f1) (stats), Wikipedia (narrative) |
| Tooling | uv, npm, Docker Compose, pre-commit, GitHub Actions |

## Repository layout

```
backend/     FastAPI app: chat API, retrieval, LLM tools
frontend/    Next.js chat UI
ingestion/   Offline pipelines that load the F1 data and the Wikipedia corpus
eval/        Golden question set for evaluating answers
docs/        Plans, data strategy and progress tracker
data/        Downloads, caches and models (git-ignored)
```

## Local setup

### Prerequisites

- Docker with Docker Compose
- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- A free [Groq API key](https://console.groq.com/keys). Gemini and OpenRouter keys are optional and add fallbacks.

### 1. Clone and configure

```bash
git clone https://github.com/RChaubey16/apexgpt.git
cd apexgpt
cp .env.example .env
```

In `.env`, set at least:

- `GROQ_API_KEY`
- the passwords: the `POSTGRES_PASSWORD` and read-only password must match the database URLs below them
- `WIKI_USER_AGENT`, a client name with your contact details (Wikipedia requires it)

### 2. Start the stack

```bash
docker compose up --build
```

This starts Postgres, the backend and the frontend with hot reload, and runs the database migrations.

| Service | URL |
|---|---|
| Chat UI | http://localhost:3000 |
| API (interactive docs at `/docs`) | http://localhost:8000 |

### 3. Load the data

A fresh clone has an empty database. In a second terminal:

```bash
# Let the LLM's read-only database role log in
(cd backend && uv sync && uv run python -m app.db.readonly_role)

cd ingestion
uv sync

# Structured F1 data, 1950–2025 (about 10 seconds)
uv run python -m structured

# Wikipedia corpus: select, fetch, clean, chunk, embed
uv run python -m narrative.select
uv run python -m narrative --selection   # about 4 hours; resumable
uv run python -m narrative.clean
uv run python -m narrative.chunk
uv run python -m narrative.embed         # about 20–40 minutes
```

Stats questions work as soon as the structured data is loaded. The Wikipedia fetch is slow on purpose, because requests are sent one at a time to follow Wikipedia's API rules. To skip it, copy `data/wikipedia/` from a machine that already has it.

### Running tests

```bash
cd backend && uv run pytest        # backend unit tests
cd ingestion && uv run pytest      # ingestion unit tests
cd frontend && npm ci && npm test  # frontend tests
```

To evaluate answers against the golden question set in `eval/` (uses LLM quota; select questions while iterating):

```bash
cd backend
uv run python -m evals run --category stats   # results and a report in data/eval/runs/
uv run python -m evals retrieval              # retrieval-only check, no LLM
```

Load and cold-start tests (production image, stub LLM, no quota): see [backend/loadtest/README.md](backend/loadtest/README.md).

To run the backend outside Docker: `cd backend && uv run uvicorn app.main:create_app --factory --reload`. For the frontend, see [frontend/README.md](frontend/README.md).

## Deployment

Production runs on a VPS with Coolify ([docker-compose.prod.yml](docker-compose.prod.yml)) and a Neon database. See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Contributing

- Create one `feature/<name>` branch from `main` per change, and open a pull request against `main`.
- Write commit messages as [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, …).
- Install the hooks with `uv tool install pre-commit`, then `(cd frontend && npm ci) && pre-commit install`. CI runs lint, tests and Docker builds on every pull request.

## Documentation

- [MVP plan](docs/MVP-PLAN.md): phases, workflow and feature breakdown
- [Features](docs/FEATURES.md): the full feature list
- [Data strategy](docs/DATA-STRATEGY.md): what data is stored and why
- [Deployment](docs/DEPLOYMENT.md): Coolify setup and production settings
- [Progress](docs/PROGRESS.md): current status and decision log

## Data attribution

Narrative content comes from [Wikipedia](https://www.wikipedia.org/) articles, licensed under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Structured data comes from [Jolpica-F1](https://github.com/jolpica/jolpica-f1), which is free for non-commercial use.
