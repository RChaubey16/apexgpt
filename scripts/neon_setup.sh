#!/usr/bin/env bash
# Set up the production database on Neon (F7.2), from the repository root:
#
#   NEON_DATABASE_URL='postgresql://owner:…@ep-….neon.tech/apexgpt?sslmode=require' \
#   NEON_READONLY_DATABASE_URL='postgresql://apexgpt_llm_reader:<16+ chars>@ep-….neon.tech/apexgpt?sslmode=require' \
#     scripts/neon_setup.sh            # REPLACE=1 to overwrite data already there
#
# 1. migrations (extensions, schema, views, the read-only role) on Neon;
# 2. the read-only role's password and LOGIN, then a check it can read the views;
# 3. the local data (DATABASE_URL in .env) copied in one transaction, with row
#    counts, the size guard and the sanity checks checked before it commits;
# 4. the size report against Neon's 1 GB.
#
# Use Neon's *direct* (non-pooled) host here; the app uses the pooled one.
# Every step is safe to re-run. URLs come from the environment only.
set -euo pipefail

: "${NEON_DATABASE_URL:?set NEON_DATABASE_URL (Neon owner connection string)}"
: "${NEON_READONLY_DATABASE_URL:?set NEON_READONLY_DATABASE_URL (apexgpt_llm_reader on Neon)}"

cd "$(dirname "$0")/.."

step() { printf '\n== %s\n' "$1"; }

step "1/4 Migrations"
(cd backend && DATABASE_URL="$NEON_DATABASE_URL" uv run alembic upgrade head)

step "2/4 Read-only role for the LLM's SQL"
(cd backend && DATABASE_URL="$NEON_DATABASE_URL" \
  READONLY_DATABASE_URL="$NEON_READONLY_DATABASE_URL" \
  uv run python -m app.db.readonly_role)

step "3/4 Data (local DATABASE_URL -> Neon)"
# A plain string, not an array: macOS's bash 3.2 treats an empty array as
# unset under `set -u`.
replace=""
if [ "${REPLACE:-}" = 1 ]; then replace="--replace"; fi
(cd ingestion && TARGET_DATABASE_URL="$NEON_DATABASE_URL" \
  uv run python -m restore $replace)

step "4/4 Size against the free tier"
(cd ingestion && DATABASE_URL="$NEON_DATABASE_URL" uv run python -m common.size_guard)

printf '\nNeon is ready. In Coolify, set DATABASE_URL and READONLY_DATABASE_URL to the\n'
printf 'pooled host (…-pooler…) with these credentials, then deploy.\n'
