"""Add LLM-friendly stats views: v_race_winners, v_driver_career,
v_season_summary, v_head_to_head_teammates.

The LLM's text-to-SQL tool (F3.5) queries these views, not the base tables, so
each view is denormalised (names next to IDs), uses readable column names and
carries COMMENT ON text describing what each column means, including the
data's limits (see docs/DATA-STRATEGY.md):

- Poles are `grid = 1`: qualifying data only exists from 1994.
- Fastest laps are only recorded from 2004 (and a few 1950s races).
- Starts are approximate: the source can't always tell a formation-lap failure
  from a lap-1 retirement.
- "Final" standings are those after a season's last loaded race.

Views hold no data; they are computed when queried. Migrations that change the
columns these views use must drop and recreate them.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

V_RACE_WINNERS = """
CREATE VIEW v_race_winners AS
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
    co.constructor_id
FROM results r
JOIN races ra ON ra.race_id = r.race_id
JOIN circuits ci ON ci.circuit_id = ra.circuit_id
JOIN drivers d ON d.driver_id = r.driver_id
JOIN constructors co ON co.constructor_id = r.constructor_id
WHERE r.position = 1
"""

V_DRIVER_CAREER = """
CREATE VIEW v_driver_career AS
WITH per_race AS (
    -- One row per driver per race (a 1950s driver could have two cars).
    SELECT
        r.driver_id,
        r.race_id,
        ra.season,
        min(r.position) AS best_position,
        bool_or(r.grid = 1) AS pole,
        -- Did the driver take the start?
        bool_or(NOT (
            s.status IN ('Withdrew', 'Did not start')
            -- Injuries/illness are non-starts only with 0 laps.
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
sprints AS (
    SELECT
        driver_id,
        count(*) AS sprint_entries,
        count(*) FILTER (WHERE position = 1) AS sprint_wins,
        sum(points) AS sprint_points
    FROM sprint_results
    GROUP BY driver_id
),
final_standings AS (
    SELECT ds.driver_id, ds.position
    FROM driver_standings ds
    -- Standings after each season's last race are the final ones.
    JOIN (
        SELECT DISTINCT ON (season) season, race_id FROM races ORDER BY season, round DESC
    ) last ON last.race_id = ds.race_id
),
titles AS (
    SELECT
        driver_id,
        count(*) FILTER (WHERE position = 1) AS championships,
        min(position) AS best_championship_position
    FROM final_standings
    GROUP BY driver_id
),
team_spells AS (
    SELECT r.driver_id, co.name, min(ra.season) AS first_season
    FROM results r
    JOIN races ra ON ra.race_id = r.race_id
    JOIN constructors co ON co.constructor_id = r.constructor_id
    GROUP BY r.driver_id, co.name
),
teams AS (
    SELECT driver_id, string_agg(name, ', ' ORDER BY first_season, name) AS teams
    FROM team_spells
    GROUP BY driver_id
),
career AS (
    SELECT
        driver_id,
        min(season) AS first_season,
        max(season) AS last_season,
        count(DISTINCT season) AS seasons,
        count(*) AS race_entries,
        count(*) FILTER (WHERE started) AS race_starts,
        count(*) FILTER (WHERE best_position = 1) AS wins,
        count(*) FILTER (WHERE best_position <= 3) AS podiums,
        count(*) FILTER (WHERE pole) AS poles,
        count(*) FILTER (WHERE fastest_lap AND season >= 2004) AS fastest_laps_since_2004,
        count(*) FILTER (WHERE started AND best_position IS NULL) AS dnfs,
        sum(points) AS race_points
    FROM per_race
    GROUP BY driver_id
)
SELECT
    d.ref AS driver_ref,
    d.forename || ' ' || d.surname AS driver_name,
    d.code AS driver_code,
    d.nationality,
    d.date_of_birth,
    c.first_season,
    c.last_season,
    c.seasons,
    c.race_entries,
    c.race_starts,
    c.wins,
    c.podiums,
    c.poles,
    c.fastest_laps_since_2004,
    c.dnfs,
    COALESCE(t.championships, 0) AS championships,
    t.best_championship_position,
    c.race_points,
    COALESCE(s.sprint_points, 0) AS sprint_points,
    c.race_points + COALESCE(s.sprint_points, 0) AS total_points,
    COALESCE(s.sprint_entries, 0) AS sprint_entries,
    COALESCE(s.sprint_wins, 0) AS sprint_wins,
    tm.teams,
    d.wikipedia_url,
    d.driver_id
FROM career c
JOIN drivers d ON d.driver_id = c.driver_id
LEFT JOIN sprints s ON s.driver_id = c.driver_id
LEFT JOIN titles t ON t.driver_id = c.driver_id
LEFT JOIN teams tm ON tm.driver_id = c.driver_id
"""

V_SEASON_SUMMARY = """
CREATE VIEW v_season_summary AS
WITH last_races AS (
    -- Standings after each season's last race are the final ones.
    SELECT DISTINCT ON (season) season, race_id FROM races ORDER BY season, round DESC
),
race_stats AS (
    SELECT
        ra.season,
        count(*) AS races,
        min(ra.date) AS first_race_date,
        max(ra.date) AS last_race_date
    FROM races ra
    GROUP BY ra.season
),
winners AS (
    SELECT ra.season, count(DISTINCT r.driver_id) AS distinct_race_winners
    FROM results r
    JOIN races ra ON ra.race_id = r.race_id
    WHERE r.position = 1
    GROUP BY ra.season
)
SELECT
    rs.season,
    rs.races,
    rs.first_race_date,
    rs.last_race_date,
    champ.driver_ref AS champion_ref,
    champ.driver_name AS champion_name,
    champ.teams AS champion_teams,
    champ.points AS champion_points,
    champ.wins AS champion_wins,
    runner.driver_ref AS runner_up_ref,
    runner.driver_name AS runner_up_name,
    runner.points AS runner_up_points,
    champ.points - runner.points AS title_margin,
    cc.constructor_ref AS constructors_champion_ref,
    cc.constructor_name AS constructors_champion_name,
    cc.points AS constructors_champion_points,
    w.distinct_race_winners,
    se.wikipedia_url
FROM race_stats rs
JOIN seasons se ON se.year = rs.season
JOIN last_races lr ON lr.season = rs.season
LEFT JOIN winners w ON w.season = rs.season
LEFT JOIN LATERAL (
    SELECT
        d.ref AS driver_ref,
        d.forename || ' ' || d.surname AS driver_name,
        ds.points,
        ds.wins,
        (
            SELECT string_agg(DISTINCT co.name, ', ')
            FROM results r
            JOIN races ra ON ra.race_id = r.race_id
            JOIN constructors co ON co.constructor_id = r.constructor_id
            WHERE r.driver_id = ds.driver_id AND ra.season = rs.season
        ) AS teams
    FROM driver_standings ds
    JOIN drivers d ON d.driver_id = ds.driver_id
    WHERE ds.race_id = lr.race_id AND ds.position = 1
    LIMIT 1
) champ ON true
LEFT JOIN LATERAL (
    SELECT d.ref AS driver_ref, d.forename || ' ' || d.surname AS driver_name, ds.points
    FROM driver_standings ds
    JOIN drivers d ON d.driver_id = ds.driver_id
    WHERE ds.race_id = lr.race_id AND ds.position = 2
    LIMIT 1
) runner ON true
LEFT JOIN LATERAL (
    SELECT co.ref AS constructor_ref, co.name AS constructor_name, cs.points
    FROM constructor_standings cs
    JOIN constructors co ON co.constructor_id = cs.constructor_id
    WHERE cs.race_id = lr.race_id AND cs.position = 1
    LIMIT 1
) cc ON true
"""

V_HEAD_TO_HEAD = """
CREATE VIEW v_head_to_head_teammates AS
WITH entries AS (
    -- One row per driver per team per race (best car for 1950s multi-car entries).
    SELECT DISTINCT ON (r.race_id, r.constructor_id, r.driver_id)
        r.race_id, r.constructor_id, r.driver_id,
        r.position, r.position_order, r.grid, r.points,
        q.position AS quali_position
    FROM results r
    LEFT JOIN qualifying q
        ON q.race_id = r.race_id AND q.driver_id = r.driver_id
        AND q.constructor_id = r.constructor_id
    ORDER BY r.race_id, r.constructor_id, r.driver_id, r.position_order
),
pairs AS (
    SELECT
        a.race_id,
        a.constructor_id,
        a.driver_id,
        b.driver_id AS teammate_id,
        -- Qualifying order: qualifying positions when both have one (1994+),
        -- otherwise starting grid (0 = pit lane, not comparable).
        CASE
            WHEN a.quali_position IS NOT NULL AND b.quali_position IS NOT NULL
                THEN a.quali_position < b.quali_position
            WHEN a.grid > 0 AND b.grid > 0 THEN a.grid < b.grid
        END AS qualified_ahead,
        CASE
            WHEN a.position IS NOT NULL AND b.position IS NOT NULL
                THEN a.position < b.position
        END AS finished_ahead,
        a.position = 1 AS won,
        b.position = 1 AS teammate_won,
        a.points,
        b.points AS teammate_points
    FROM entries a
    JOIN entries b
        ON b.race_id = a.race_id
        AND b.constructor_id = a.constructor_id
        AND b.driver_id <> a.driver_id
)
SELECT
    ra.season,
    co.ref AS constructor_ref,
    co.name AS constructor_name,
    d.ref AS driver_ref,
    d.forename || ' ' || d.surname AS driver_name,
    t.ref AS teammate_ref,
    t.forename || ' ' || t.surname AS teammate_name,
    count(*) AS races_together,
    count(*) FILTER (WHERE p.qualified_ahead) AS qualified_ahead,
    count(*) FILTER (WHERE NOT p.qualified_ahead) AS qualified_behind,
    count(*) FILTER (WHERE p.finished_ahead) AS finished_ahead,
    count(*) FILTER (WHERE NOT p.finished_ahead) AS finished_behind,
    count(*) FILTER (WHERE p.won) AS wins,
    count(*) FILTER (WHERE p.teammate_won) AS teammate_wins,
    sum(p.points) AS points,
    sum(p.teammate_points) AS teammate_points,
    d.driver_id,
    t.driver_id AS teammate_id,
    co.constructor_id
FROM pairs p
JOIN races ra ON ra.race_id = p.race_id
JOIN constructors co ON co.constructor_id = p.constructor_id
JOIN drivers d ON d.driver_id = p.driver_id
JOIN drivers t ON t.driver_id = p.teammate_id
GROUP BY ra.season, co.constructor_id, d.driver_id, t.driver_id
"""

COMMENTS = {
    "v_race_winners": (
        "One row per race win (1950s shared drives: one row per winning driver).",
        {
            "race_time": "Winner's total race time as H:MM:SS.mmm; NULL when not recorded.",
            "time_ms": "Winner's total race time in milliseconds.",
            "grid": "Starting position (0 = pit lane).",
            "points": "Points the winner scored in this race.",
        },
    ),
    "v_driver_career": (
        "One row per driver who has a race result: career totals over the loaded seasons.",
        {
            "race_entries": "Races with a result row (did-not-qualify entries are excluded).",
            "race_starts": "Approximate starts: entries minus withdrawals/did-not-start and "
            "pre-race injuries. May exceed official counts by 1-3 when a car failed on the "
            "formation lap.",
            "wins": "Races won (a shared 1950s win counts once).",
            "podiums": "Races finished in the top 3.",
            "poles": "Races started from grid position 1 (qualifying data only exists from 1994, "
            "so poles use the grid).",
            "fastest_laps_since_2004": "Fastest laps in races from 2004 onwards only; "
            "earlier fastest laps are not in the data.",
            "dnfs": "Races started but not classified (retirements and disqualifications).",
            "championships": "Drivers' titles (position 1 after a season's last race).",
            "best_championship_position": "Best final drivers' championship position; "
            "NULL if never classified.",
            "race_points": "Grand Prix points as scored, including points later dropped "
            "under best-results rules.",
            "sprint_points": "Sprint race points (2021 onwards).",
            "total_points": "race_points + sprint_points.",
            "teams": "Constructors driven for, in order of first season.",
        },
    ),
    "v_season_summary": (
        "One row per season: champions, runner-up and title margin, from the standings "
        "after the season's last loaded race.",
        {
            "races": "Championship races held.",
            "champion_teams": "Constructor(s) the drivers' champion raced for that season.",
            "title_margin": "Champion's points minus the runner-up's.",
            "constructors_champion_name": "NULL before 1958 (no constructors' championship).",
            "distinct_race_winners": "Number of different drivers who won a race.",
        },
    ),
    "v_head_to_head_teammates": (
        "Teammate comparisons per season and team, in both directions (filter on "
        "driver_ref and teammate_ref). Only races where both drove for the team count.",
        {
            "races_together": "Races where both drivers had a result for this team.",
            "qualified_ahead": "Races where the driver qualified ahead (qualifying from 1994, "
            "starting grid before).",
            "finished_ahead": "Races where both were classified and the driver finished ahead.",
            "points": "Driver's points in the races together.",
            "teammate_points": "Teammate's points in the races together.",
        },
    ),
}


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def upgrade() -> None:
    for ddl in (V_RACE_WINNERS, V_DRIVER_CAREER, V_SEASON_SUMMARY, V_HEAD_TO_HEAD):
        op.execute(ddl)
    for view, (view_comment, columns) in COMMENTS.items():
        op.execute(f"COMMENT ON VIEW {view} IS {_quote(view_comment)}")
        for column, comment in columns.items():
            op.execute(f"COMMENT ON COLUMN {view}.{column} IS {_quote(comment)}")


def downgrade() -> None:
    for view in reversed(list(COMMENTS)):
        op.execute(f"DROP VIEW IF EXISTS {view}")
