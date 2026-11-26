# Deploying ApexGPT

ApexGPT runs on a VPS with **Coolify** (backend and frontend containers) and a **Neon** Postgres database. The production stack is [`docker-compose.prod.yml`](../docker-compose.prod.yml).

The deployment phase is built in steps:

- F7.1: production compose
- F7.2: Neon setup and data restore
- F7.3: weekly backups (see "Backups")
- F7.4: production smoke test (see "Smoke test")

## What runs where

| Piece | Where | Notes |
|---|---|---|
| Frontend (Next.js) | VPS, `frontend` service | Static build; the backend URL is baked in at build time |
| Backend (FastAPI) | VPS, `backend` service | Runs the migrations on start, then serves. The search models are in the image |
| Database | Neon (free tier) | Pooled connection string. Also the read-only role for the LLM's SQL |
| LLMs | Groq, then Gemini and OpenRouter | Free tiers, API keys only |

Budget: backend 768 MB / 1 CPU (measured peak ~614 MiB, see [backend/loadtest/README.md](../backend/loadtest/README.md)); frontend 384 MB (~35 MiB measured).

## Neon setup (once, before the first deploy)

1. **Create the project** in the Neon console on the free tier, in the region closest to the VPS, with Postgres 18. Create a database for ApexGPT (e.g. `apexgpt`), or use the default `neondb`.
2. **Copy two connection strings** from **Connect**, both for that database's owner role:
   - the **direct** one, used by the setup below;
   - the **pooled** one (its host contains `-pooler`), used by the app in Coolify.

   Both end in `?sslmode=require`.
3. **Pick a password for the read-only role** (16+ characters), e.g. `openssl rand -base64 24 | tr -d '/+='`.
   - The migrations create the role `apexgpt_llm_reader`, and the setup gives it this password.
   - **Don't create the role in the Neon console.** A role made there belongs to Neon's control plane, so the migrations can't set its limits (`permission denied to alter role`). If you already made one, delete it in the console and run the setup again.
   - Its URL is the owner's **direct** URL with only the user and password replaced: same host, database and query.
4. **Run the setup** from the repository root, on the machine that has the loaded local database:

   ```bash
   NEON_DATABASE_URL='postgresql://<owner>:<pw>@<direct host>/apexgpt?sslmode=require' \
   NEON_READONLY_DATABASE_URL='postgresql://apexgpt_llm_reader:<reader pw>@<direct host>/apexgpt?sslmode=require' \
     scripts/neon_setup.sh
   ```

   It does four things:
   - runs the migrations (the `vector` and `unaccent` extensions, the schema, the views, the role);
   - sets the read-only role's password and checks it can read the views;
   - copies the local data;
   - prints the size against the 1 GB free tier.

   The copy is one transaction: row counts, the size guard and the 30 sanity checks must pass before it commits, or nothing changes. `REPLACE=1` overwrites data that's already there.

   Rehearsed locally on a fresh database: 16 tables and 116,637 rows in ~11 s, 80.6 MB in total. The backend's real-data tests then passed against the copy.
5. **For Coolify**, use the **pooled** host with the same credentials:
   - `DATABASE_URL`: the owner;
   - `READONLY_DATABASE_URL`: `apexgpt_llm_reader`.

**Updating the data later** (a new season, or a corpus change): load it locally, check it, then run `REPLACE=1 scripts/neon_setup.sh`. A failure leaves Neon as it was.

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
   | `DATABASE_URL` | yes | Neon **pooled** connection string with `?sslmode=require` (owner role) |
   | `READONLY_DATABASE_URL` | yes | The same pooled host, as `apexgpt_llm_reader` with its password |
   | `CORS_ORIGINS` | yes | The frontend's origin, e.g. `https://apexgpt.example.com` |
   | `NEXT_PUBLIC_SITE_URL` | yes | The frontend's own public URL, e.g. `https://apexgpt.example.com`, for the canonical link, share cards, `robots.txt` and the sitemap. Also a **build** argument |
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

## Smoke test

After every deploy, from `backend/`:

```bash
uv run python -m evals smoke --frontend https://apexgpt.ruturaj.xyz --api https://apexgpt-api.ruturaj.xyz
```

It checks the live site over HTTPS, the way a browser uses it:
- **The backend:** `/health/ready` and its latency, `/health` in production, `/docs` hidden, CORS allowing only the frontend's origin.
- **The frontend:** its page and its `/api/health`.
- **Answers:** the golden questions marked `smoke: true` (8), asked through `POST /api/chat` and scored without an LLM judge: answer values, tools, cited sources, and the follow-up rewrite.

How it behaves:
- It exits 1 if anything fails. The report, with failed answers' text, goes to `data/eval/smoke/`.
- Questions are 11 s apart, to stay under the per-IP limit of 6 answers a minute. A run takes ~2 minutes and about 50k LLM tokens.
- Re-runs within 24 hours are served from the production cache (the report shows "cached"), so they cost almost nothing.

**Neon's wake-up:** run it after 5+ idle minutes and the first `/health/ready` includes Neon resuming. Measured on 2026-11-26: **1.81 s cold** against **~0.44 s warm**, so about 1.4 s of wake-up. The frontend calls `/health/ready` on page load, so a visitor usually pays that before asking anything.

## Client addresses

The per-IP rate limits key on the visitor's address, which Traefik sends in `X-Forwarded-For`. The backend trusts that header only from `FORWARDED_ALLOW_IPS`.

The default is the private ranges (`10.0.0.0/8,172.16.0.0/12,192.168.0.0/16`). That's safe because the backend is reachable only from the stack's private Docker network: nothing in `docker-compose.prod.yml` is published with `ports:`.

Never set it to `*`, and don't publish the backend's port. Either would let a client choose its own rate-limit key.

Checked locally (F7.1): six requests from one forwarded address, then a 429 for it, while a second address behind the same proxy was unaffected.

## Logs

The backend writes JSON lines to `/app/logs/apexgpt.log` on the `apexgpt-logs` volume, rotated at 10 MB × 5. The volume survives deploys. The logs hold users' questions (no IP addresses).

## Backups

[`.github/workflows/backup.yml`](../.github/workflows/backup.yml) runs every Sunday at 03:17 UTC, and on demand from **Actions → Weekly backup → Run workflow**. Each run:

1. Takes a `pg_dump` of Neon (Postgres 18 tools, in the `pgvector/pgvector:0.8.1-pg18` image).
2. Restores it into a scratch Postgres on the runner. **Every table's row count must match Neon's**, or the run fails.
3. Encrypts it (gpg, AES-256) and keeps it as an artifact for 5 weeks. The repository is public, and anyone signed in to GitHub can download a public repo's artifacts, so only the encrypted file is ever uploaded. The dump includes the users' feedback.
4. Deletes feedback older than 90 days (`python -m app.feedback purge`).

The work is done by [`scripts/backup.sh`](../scripts/backup.sh), which also runs locally. Rehearsed locally: 18 tables and 116,642 rows dumped, restored and matched, then encrypted to 33 MB, in ~11 s.

GitHub emails you when a scheduled run fails. It also disables scheduled workflows after 60 days without commits; re-enable it under **Actions** if that happens.

### Setting it up

Add two **repository secrets**. Use the GitHub CLI, which prompts for each value without echoing it, or the web UI under **Settings → Secrets and variables → Actions**:

```bash
gh secret set NEON_BACKUP_DATABASE_URL   # Neon's direct (non-pooled) owner URL
gh secret set BACKUP_PASSPHRASE          # 20+ characters, e.g. openssl rand -base64 30
```

**Keep a copy of the passphrase outside GitHub** (a password manager). GitHub never shows a secret again, and without it no backup can be decrypted.

Then run the workflow once by hand:

```bash
gh workflow run backup.yml && gh run watch
```

### Restoring a backup

1. **Download and decrypt** (asks for the passphrase without echoing it):

   ```bash
   gh run download <run id> --dir backup     # or download the artifact from the run page
   read -rs "BACKUP_PASSPHRASE?Passphrase: " && echo && export BACKUP_PASSPHRASE
   docker run --rm -e BACKUP_PASSPHRASE -v "$PWD/backup:/b" pgvector/pgvector:0.8.1-pg18 \
     sh -c 'export GNUPGHOME=$(mktemp -d); f=$(ls /b/*/*.dump.gpg | head -1);
            printf %s "$BACKUP_PASSPHRASE" | gpg --batch --pinentry-mode loopback \
              --passphrase-fd 0 --decrypt --output /b/apexgpt.dump "$f"'
   ```

   A wrong passphrase fails with `Bad session key`.
2. **Prepare the target** (the same Neon database, or a new one):

   ```bash
   (cd backend && DATABASE_URL="$NEON_DATABASE_URL" uv run alembic upgrade head)
   ```

   This creates the extensions and the `apexgpt_llm_reader` role that the backup's grants refer to.
3. **Restore.** This replaces every object, data and grants included, with the backup's copy, in one transaction:

   ```bash
   docker run --rm -e NEON_DATABASE_URL -v "$PWD/backup:/b" pgvector/pgvector:0.8.1-pg18 \
     bash -c 'set -o pipefail
       pg_restore --clean --if-exists --no-owner --file=- /b/apexgpt.dump |
       sed -E "/^ALTER TABLE ONLY [^ ]+ ALTER COLUMN [^ ]+ SET \(pg_attver=[0-9]+\);\$/d" |
       psql "$NEON_DATABASE_URL" -X -q --single-transaction -v ON_ERROR_STOP=1 >/dev/null'
   ```

   - The `sed` drops Neon's internal column option (`pg_attver`). A dump of Neon contains it, but stock Postgres rejects it, and Neon doesn't need it restored. This pipeline also restores into any other Postgres 18 with pgvector.
   - It's exactly what the weekly run's restore check executes.

4. **On a new database only,** set the read-only role's password: step 2/4 of `scripts/neon_setup.sh`, i.e. `python -m app.db.readonly_role`.
5. **Delete `backup/` afterwards.** The decrypted dump holds the users' feedback.

Rehearsed locally on a fresh database: the restored copy matched the original (14,581 chunks, 25,873 results, revision 0009), and the read-only role could read the views.

Neon's free tier also keeps a short point-in-time restore window (see the Neon console). The weekly backup covers anything older, or a lost project.
