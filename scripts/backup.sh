#!/usr/bin/env bash
# Back up the database, prove the backup restores, and encrypt it (F7.3).
# The weekly workflow (.github/workflows/backup.yml) runs this; it also runs
# locally. Environment:
#
#   SOURCE_DATABASE_URL   database to back up (Neon: the direct owner URL)
#   VERIFY_DATABASE_URL   an EMPTY scratch database the dump is restored into
#                         (its contents are replaced)
#   BACKUP_PASSPHRASE     encrypts the dump (AES-256, gpg symmetric)
#   OUT_DIR               where apexgpt-<UTC date>.dump.gpg is written (default .)
#   PG_IMAGE              image with pg_dump/pg_restore/psql matching the
#                         server's major version (default pgvector/pgvector:0.8.1-pg18)
#   DOCKER_NETWORK        docker network for the tool containers (default host)
#
# The dump is pg_dump's custom format: everything, including feedback. The
# repository is public, so only the encrypted file leaves this machine; the
# plain dump is deleted when the script exits. Every table's row count in the
# restored copy must equal the source's, or the script fails.
set -euo pipefail

# Required settings, by name. A function rather than the ${VAR:?message} form,
# which secret scanners read as a hardcoded password for the passphrase.
require() {
  if [ -z "${!1:-}" ]; then
    echo "error: set $1${2:+ ($2)}" >&2
    exit 2
  fi
}
require SOURCE_DATABASE_URL
require VERIFY_DATABASE_URL "an empty scratch database"
require BACKUP_PASSPHRASE
OUT_DIR="${OUT_DIR:-.}"
PG_IMAGE="${PG_IMAGE:-pgvector/pgvector:0.8.1-pg18}"
DOCKER_NETWORK="${DOCKER_NETWORK:-host}"

if [ "${#BACKUP_PASSPHRASE}" -lt 20 ]; then
  echo "error: BACKUP_PASSPHRASE must be at least 20 characters" >&2
  exit 2
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$OUT_DIR"
out="$OUT_DIR/apexgpt-$stamp.dump.gpg"

# A Postgres client in the server's version. URLs go in as environment
# variables, never as command-line arguments.
pg() {
  docker run --rm -i --network "$DOCKER_NETWORK" \
    -e SOURCE_DATABASE_URL -e VERIFY_DATABASE_URL -e BACKUP_PASSPHRASE \
    -v "$work:/work" "$PG_IMAGE" "$@"
}

# Row counts of every table in public, as "table count" lines.
counts() {
  pg sh -c "psql \"\$$1\" -XAtq -v ON_ERROR_STOP=1 -c \"
    SELECT format('SELECT %L, count(*) FROM %I;', relname, relname)
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r' ORDER BY relname\" \
    | psql \"\$$1\" -XAtq -F ' ' -v ON_ERROR_STOP=1"
}

echo "== Dumping"
pg sh -c 'pg_dump "$SOURCE_DATABASE_URL" --format=custom --compress=6 \
  --no-owner --file=/work/apexgpt.dump'
size=$(wc -c < "$work/apexgpt.dump" | tr -d ' ')
echo "dump: $((size / 1000000)) MB"

echo "== Checking the dump restores"
# --no-privileges: the scratch database has none of production's roles.
pg sh -c 'PGOPTIONS="-c client_min_messages=warning" \
  psql "$VERIFY_DATABASE_URL" -XAtq -v ON_ERROR_STOP=1 \
  -c "DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public"'
# Through SQL text, without Neon's internal column option: a dump of Neon
# contains `ALTER TABLE ONLY t ALTER COLUMN c SET (pg_attver=N);` lines, which
# stock Postgres rejects ("unrecognized parameter"). docs/DEPLOYMENT.md
# restores the same way, so this checks exactly what a recovery would run.
pg bash -c 'set -o pipefail; pg_restore --no-owner --no-privileges --file=- /work/apexgpt.dump |
  sed -E "/^ALTER TABLE ONLY [^ ]+ ALTER COLUMN [^ ]+ SET \(pg_attver=[0-9]+\);\$/d" |
  PGOPTIONS="-c client_min_messages=warning" \
    psql "$VERIFY_DATABASE_URL" -X -q --single-transaction -v ON_ERROR_STOP=1 >/dev/null'
counts SOURCE_DATABASE_URL > "$work/source.txt"
counts VERIFY_DATABASE_URL > "$work/restored.txt"
if ! diff -u "$work/source.txt" "$work/restored.txt"; then
  echo "error: the restored copy's row counts differ from the source" >&2
  exit 1
fi
tables=$(wc -l < "$work/source.txt" | tr -d ' ')
rows=$(awk '{ s += $2 } END { print s }' "$work/source.txt")
echo "restored $tables tables, $rows rows: counts match the source"

echo "== Encrypting"
# gpg from the same image, so encrypting and decrypting behave the same on a
# runner and on a laptop. The passphrase is read from the environment.
pg sh -c 'export GNUPGHOME=$(mktemp -d) && printf %s "$BACKUP_PASSPHRASE" |
  gpg --batch --yes --quiet --pinentry-mode loopback --passphrase-fd 0 \
    --symmetric --cipher-algo AES256 --output /work/apexgpt.dump.gpg /work/apexgpt.dump'
mv "$work/apexgpt.dump.gpg" "$out"
echo "backup: $out ($(( $(wc -c < "$out" | tr -d ' ') / 1000000 )) MB, encrypted)"
