"""Add the read-only role the LLM's SQL tool connects as (apexgpt_llm_reader).

The role can only SELECT the stats views (v_*). Views read the base tables with
their owner's rights, so the role needs (and gets) no table privileges at all.
Role defaults bound what a single query can do:

- statement_timeout 5s, lock_timeout 1s, idle_in_transaction_session_timeout 10s
- default_transaction_read_only on
- at most 5 concurrent connections

The role is created NOLOGIN with no password: credentials never live in
migrations. `python -m app.db.readonly_role` enables login with the password
from READONLY_DATABASE_URL.

These defaults are a backstop, not the only guard: any session may SET its own
statement_timeout (or call set_config), so the SQL tool (F3.5) must only run
validated SELECTs on the views.

Roles are cluster-wide, so this migration is idempotent across databases on the
same server (e.g. test databases): it creates the role only if missing, and the
downgrade drops it only when no other database still grants it anything.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Static SQL (no string building). The role name is also used by
# app/db/readonly_role.py (ROLE); keep them in sync.
CREATE_ROLE = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'apexgpt_llm_reader') THEN
        CREATE ROLE apexgpt_llm_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION CONNECTION LIMIT 5;
    END IF;
END
$$
"""

ROLE_SETTINGS = (
    "ALTER ROLE apexgpt_llm_reader SET statement_timeout = '5s'",
    "ALTER ROLE apexgpt_llm_reader SET lock_timeout = '1s'",
    "ALTER ROLE apexgpt_llm_reader SET idle_in_transaction_session_timeout = '10s'",
    "ALTER ROLE apexgpt_llm_reader SET default_transaction_read_only = on",
)

GRANTS = (
    "GRANT USAGE ON SCHEMA public TO apexgpt_llm_reader",
    "GRANT SELECT ON v_race_winners, v_driver_career, v_season_summary, "
    "v_head_to_head_teammates TO apexgpt_llm_reader",
)

REVOKES = (
    "REVOKE SELECT ON v_race_winners, v_driver_career, v_season_summary, "
    "v_head_to_head_teammates FROM apexgpt_llm_reader",
    "REVOKE USAGE ON SCHEMA public FROM apexgpt_llm_reader",
)

# Another database on this server may still grant the role privileges.
DROP_ROLE_IF_UNUSED = """
DO $$
BEGIN
    DROP ROLE IF EXISTS apexgpt_llm_reader;
EXCEPTION WHEN dependent_objects_still_exist THEN
    RAISE NOTICE 'role apexgpt_llm_reader is still used by another database; kept';
END
$$
"""


def upgrade() -> None:
    op.execute(CREATE_ROLE)
    for statement in ROLE_SETTINGS + GRANTS:
        op.execute(statement)


def downgrade() -> None:
    for statement in REVOKES:
        op.execute(statement)
    op.execute(DROP_ROLE_IF_UNUSED)
