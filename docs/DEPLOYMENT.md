# Deploying ApexGPT

ApexGPT runs on a VPS with **Coolify** (backend and frontend containers) and a **Neon** Postgres database. The production stack is [`docker-compose.prod.yml`](../docker-compose.prod.yml).

The deployment phase is built in steps:

- **F7.1: production compose** (this guide)
- F7.2: Neon setup and data restore. Until it lands, there's no production database to point at.
- F7.3: weekly backups
- F7.4: production smoke test

## What runs where

| Piece | Where | Notes |
|---|---|---|
| Frontend (Next.js) | VPS, `frontend` service | Static build; the backend URL is baked in at build time |
| Backend (FastAPI) | VPS, `backend` service | Runs the migrations on start, then serves. The search models are in the image |
| Database | Neon (free tier) | Pooled connection string. Also the read-only role for the LLM's SQL |
| LLMs | Groq, then Gemini and OpenRouter | Free tiers, API keys only |

Budget: backend 768 MB / 1 CPU (measured peak ~614 MiB, see [backend/loadtest/README.md](../backend/loadtest/README.md)); frontend 384 MB (~35 MiB measured).

## Coolify setup

1. **New resource:** Public or Private Repository → this repo, branch `main`.
2. **Build pack:** Docker Compose, with:
   - Base Directory: `/`
   - Docker Compose Location: `/docker-compose.prod.yml`
3. **Domains** (in the resource's service list), each with its internal port:
   - `frontend`: `https://apexgpt.example.com:3000`
   - `backend`: `https://api.apexgpt.example.com:8000`

   Without your own domain yet, Coolify's generated domain (e.g. `sslip.io`) works the same way.
4. **Environment variables:** the ones marked *required* block the deploy until they're set. Use the same domains as step 3:

   | Variable | Required | Value |
   |---|---|---|
   | `DATABASE_URL` | yes | Neon **pooled** connection string with `?sslmode=require` (F7.2) |
   | `READONLY_DATABASE_URL` | yes | The same host as the `apexgpt_llm_reader` role (F7.2) |
   | `CORS_ORIGINS` | yes | The frontend's origin, e.g. `https://apexgpt.example.com` |
   | `NEXT_PUBLIC_API_URL` | yes | The backend's URL, e.g. `https://api.apexgpt.example.com`. It's a **build** argument: change it and the frontend must be rebuilt |
   | `GROQ_API_KEY` | yes | Groq API key (secret) |
   | `GEMINI_API_KEY`, `OPENROUTER_API_KEY` | no | Fallback providers (secrets). Blank turns a provider off |
   | `FORWARDED_ALLOW_IPS` | no | Default: the private ranges. See "Client addresses" below |
   | `RATE_LIMIT_CHAT`, `RATE_LIMIT_FEEDBACK`, `ANSWER_CACHE_*`, `LLM_*`, `LOG_*` | no | Defaults as in development |

5. **Deploy.** The backend logs `alembic upgrade head` and then `Uvicorn running`. Both services turn healthy, from `/health` and `/api/health`.

## After the first deploy

- **Check the memory limits are applied:**

  ```bash
  docker stats --no-stream
  ```

  Run it on the VPS. The backend should show `/ 768MiB` and the frontend `/ 384MiB`. Coolify's docs don't say whether it honours `deploy.resources.limits`.
- **Check the backend:** `https://api…/health/ready` should return `{"status": "ok", "database": "ok"}`. `/docs` returns 404 in production.
- **Check the frontend:** the page should show "All systems go". That calls `/health/ready`, which wakes Neon.

## Client addresses

The per-IP rate limits key on the visitor's address, which Traefik sends in `X-Forwarded-For`. The backend trusts that header only from `FORWARDED_ALLOW_IPS`.

The default is the private ranges (`10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`). That's safe because the backend is reachable only from the stack's private Docker network: nothing in `docker-compose.prod.yml` is published with `ports:`.

Never set it to `*`, and don't publish the backend's port. Either would let a client choose its own rate-limit key.

Checked locally (F7.1): six requests from one forwarded address, then a 429 for it, while a second address behind the same proxy was unaffected.

## Logs

The backend writes JSON lines to `/app/logs/apexgpt.log` on the `apexgpt-logs` volume, rotated at 10 MB × 5. The volume survives deploys. The logs hold users' questions (no IP addresses).
