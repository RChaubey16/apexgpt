"""Add v_driver_season (per-season driver stats) and v_race_winners.circuit_locality
for the LLM's stats tool (F6.3).

The four views from 0004 have career totals (v_driver_career) and race winners
(v_race_winners), but nothing per season, so "How many poles did Senna take in
1988?" couldn't be answered (the model answered 7, the wins from pole; the data
has 13). This view has one row per driver per season, computed like
v_driver_career (same per-race rules for starts, poles and DNFs), plus the final
championship position and the points that counted under best-results rules.

The read-only LLM role gets SELECT on it, like the other views (0005).

v_race_winners gains circuit_locality (the town: "Imola", "Monza", "Spa"): the
model knows circuits by town, but circuit_name is official ("Autodromo Enzo e
Dino Ferrari"), so "the most wins at Imola" found nothing. The column is added at
the end with CREATE OR REPLACE VIEW, which keeps the view's grants and comments.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-26
"""

import importlib.util
from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

READER_ROLE = "apexgpt_llm_reader"

V_DRIVER_SEASON = """
CREATE VIEW v_driver_season AS
WITH per_race AS (
    -- One row per driver per race (a 1950s driver could have two cars), with
    -- the same rules as v_driver_career.
    SELECT
        r.driver_id,
        r.race_id,
        ra.season,
        min(r.position) AS best_position,
        bool_or(r.grid = 1) AS pole,
        bool_or(NOT (
            s.status IN ('Withdrew', 'Did not start')
            OR (r.laps = 0 AND s.status IN
                ('Injury', 'Injured', 'Illness', 'Eye injury', 'Fatal accident'))
        )) AS started,
        bool_or(r.fastest_lap_rank = 1) AS fastest_lap,
        sum(r.points) AS points
    FROM results r
    JOIN races ra ON ra.race_id = r.race_id
    JOIN status s ON s.status_id = r.status_id
    GROUP BY r.driver_id, r.race_id, ra.season
),
season_totals AS (
    SELECT
        driver_id,
        season,
        count(*) AS race_entries,
        count(*) FILTER (WHERE started) AS race_starts,
        count(*) FILTER (WHERE best_position = 1) AS wins,
        count(*) FILTER (WHERE best_position <= 3) AS podiums,
        count(*) FILTER (WHERE pole) AS poles,
        count(*) FILTER (WHERE fastest_lap) AS fastest_laps,
        count(*) FILTER (WHERE started AND best_position IS NULL) AS dnfs,
        sum(points) AS race_points
    FROM per_race
    GROUP BY driver_id, season
),
sprints AS (
    SELECT sr.driver_id, ra.season, sum(sr.points) AS sprint_points
    FROM sprint_results sr
    JOIN races ra ON ra.race_id = sr.race_id
    GROUP BY sr.driver_id, ra.season
),
last_races AS (
    SELECT DISTINCT ON (season) season, race_id FROM races ORDER BY season, round DESC
),
final_standings AS (
    SELECT lr.season, ds.driver_id, ds.position, ds.points
    FROM driver_standings ds
    JOIN last_races lr ON lr.race_id = ds.race_id
),
team_spells AS (
    SELECT r.driver_id, ra.season, co.name, min(ra.round) AS first_round
    FROM results r
    JOIN races ra ON ra.race_id = r.race_id
    JOIN constructors co ON co.constructor_id = r.constructor_id
    GROUP BY r.driver_id, ra.season, co.name
),
teams AS (
    SELECT driver_id, season, string_agg(name, ', ' ORDER BY first_round, name) AS teams
    FROM team_spells
    GROUP BY driver_id, season
)
SELECT
    st.season,
    d.ref AS driver_ref,
    d.forename || ' ' || d.surname AS driver_name,
    d.nationality,
    tm.teams,
    st.race_entries,
    st.race_starts,
    st.wins,
    st.podiums,
    st.poles,
    st.fastest_laps,
    st.dnfs,
    st.race_points,
    COALESCE(sp.sprint_points, 0) AS sprint_points,
    st.race_points + COALESCE(sp.sprint_points, 0) AS total_points,
    fs.position AS championship_position,
    fs.points AS championship_points,
    d.driver_id
FROM season_totals st
JOIN drivers d ON d.driver_id = st.driver_id
LEFT JOIN sprints sp ON sp.driver_id = st.driver_id AND sp.season = st.season
LEFT JOIN final_standings fs ON fs.driver_id = st.driver_id AND fs.season = st.season
LEFT JOIN teams tm ON tm.driver_id = st.driver_id AND tm.season = st.season
"""

VIEW_COMMENT = (
    "One row per driver per season: that season's results and final championship "
    "position. Use it for any per-season question (wins, poles, podiums or points "
    "in a given year)."
)

COLUMN_COMMENTS = {
    "teams": "Constructor(s) the driver raced for that season, in order.",
    "race_entries": "Races with a result row that season.",
    "race_starts": "Approximate starts (as in v_driver_career).",
    "wins": "Races won that season.",
    "podiums": "Races finished in the top 3 that season.",
    "poles": "Races started from grid position 1 that season.",
    "fastest_laps": "Fastest laps that season; only recorded from 2004 (and a few "
    "1950s races), so 0 before 2004 means not recorded, not none.",
    "dnfs": "Races started but not classified that season.",
    "race_points": "Grand Prix points as scored that season, including points later "
    "dropped under best-results rules.",
    "sprint_points": "Sprint race points that season (2021 onwards).",
    "total_points": "race_points + sprint_points.",
    "championship_position": "Final drivers' championship position; NULL if not "
    "classified.",
    "championship_points": "Points that counted in the final standings (after "
    "best-results rules, e.g. only the best 11 results in 1988), so it can be lower "
    "than race_points.",
}


V_RACE_WINNERS_WITH_LOCALITY = """
CREATE OR REPLACE VIEW v_race_winners AS
SELECT
    ra.season,
    ra.round,
    ra.name AS race_name,
    ra.date AS race_date,
    ci.name AS circuit_name,
    ci.country AS circuit_country,
    d.ref AS driver_ref,
    d.forename || ' ' || d.surname AS driver_name,
    d.nationality AS driver_nationality,
    co.ref AS constructor_ref,
    co.name AS constructor_name,
    r.grid,
    r.laps,
    r.time_ms,
    to_char(make_interval(secs => r.time_ms / 1000.0), 'FMHH24:MI:SS.MS') AS race_time,
    r.points,
    ra.wikipedia_url,
    ra.race_id,
    d.driver_id,
    co.constructor_id,
    ci.locality AS circuit_locality
FROM results r
JOIN races ra ON ra.race_id = r.race_id
JOIN circuits ci ON ci.circuit_id = ra.circuit_id
JOIN drivers d ON d.driver_id = r.driver_id
JOIN constructors co ON co.constructor_id = r.constructor_id
WHERE r.position = 1
"""

LOCALITY_COMMENT = (
    "Town or area of the circuit (e.g. Imola, Monza, Spa, Austin); "
    "circuit_name is the official name."
)


def _migration_0004():  # noqa: ANN202
    """0004's view definitions, to restore v_race_winners on downgrade."""
    path = Path(__file__).with_name("0004_add_stats_views.py")
    spec = importlib.util.spec_from_file_location("migration_0004", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(V_DRIVER_SEASON)
    op.execute(f"COMMENT ON VIEW v_driver_season IS {_quote(VIEW_COMMENT)}")
    for column, comment in COLUMN_COMMENTS.items():
        op.execute(f"COMMENT ON COLUMN v_driver_season.{column} IS {_quote(comment)}")
    op.execute(f"GRANT SELECT ON v_driver_season TO {READER_ROLE}")

    op.execute(V_RACE_WINNERS_WITH_LOCALITY)
    op.execute(
        "COMMENT ON COLUMN v_race_winners.circuit_locality IS "
        + _quote(LOCALITY_COMMENT)
    )


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS v_driver_season")

    # A view can't lose a column in place: recreate 0004's v_race_winners.
    m0004 = _migration_0004()
    op.execute("DROP VIEW v_race_winners")
    op.execute(m0004.V_RACE_WINNERS)
    view_comment, columns = m0004.COMMENTS["v_race_winners"]
    op.execute(f"COMMENT ON VIEW v_race_winners IS {_quote(view_comment)}")
    for column, comment in columns.items():
        op.execute(f"COMMENT ON COLUMN v_race_winners.{column} IS {_quote(comment)}")
    op.execute(f"GRANT SELECT ON v_race_winners TO {READER_ROLE}")
