"""Read the structured F1 data the article selection rules need (read-only)."""

import psycopg

from narrative.selection import (
    CircuitRow,
    ConstructorRow,
    DriverRow,
    EntityRows,
    RaceRow,
    SeasonRow,
)

# Career numbers come from the stats view, so "notable" uses the same
# definitions as the answers (podiums count a race once, starts exclude
# withdrawals). Drivers without results still get a row (LEFT JOIN).
_DRIVERS = """
SELECT d.driver_id, d.forename || ' ' || d.surname, d.wikipedia_url,
       coalesce(v.championships, 0), coalesce(v.wins, 0),
       coalesce(v.podiums, 0), coalesce(v.race_starts, 0)
FROM drivers d
LEFT JOIN v_driver_career v ON v.driver_id = d.driver_id
ORDER BY d.driver_id
"""

_CONSTRUCTORS = """
SELECT c.constructor_id, c.name, c.wikipedia_url,
       coalesce(array_agg(DISTINCT ra.season) FILTER (WHERE ra.season IS NOT NULL),
                '{}'),
       count(*) FILTER (WHERE r.position = 1),
       EXISTS (
           SELECT 1 FROM v_season_summary s
           WHERE s.constructors_champion_ref = c.ref
       )
FROM constructors c
LEFT JOIN results r ON r.constructor_id = c.constructor_id
LEFT JOIN races ra ON ra.race_id = r.race_id
GROUP BY c.constructor_id
ORDER BY c.constructor_id
"""


def read_entity_rows(conn: psycopg.Connection) -> EntityRows:
    with conn.cursor() as cur:
        cur.execute("SELECT year, wikipedia_url FROM seasons ORDER BY year")
        seasons = [SeasonRow(*row) for row in cur.fetchall()]
        cur.execute(
            "SELECT race_id, season, circuit_id, name, wikipedia_url "
            "FROM races ORDER BY race_id"
        )
        races = [RaceRow(*row) for row in cur.fetchall()]
        cur.execute(
            "SELECT circuit_id, name, wikipedia_url FROM circuits ORDER BY circuit_id"
        )
        circuits = [CircuitRow(*row) for row in cur.fetchall()]
        cur.execute(_DRIVERS)
        drivers = [DriverRow(*row) for row in cur.fetchall()]
        cur.execute(_CONSTRUCTORS)
        constructors = [
            ConstructorRow(cid, name, url, frozenset(seasons_), wins, champion)
            for cid, name, url, seasons_, wins, champion in cur.fetchall()
        ]
        cur.execute("SELECT ref, driver_id FROM drivers")
        driver_refs = dict(cur.fetchall())
        cur.execute("SELECT ref, constructor_id FROM constructors")
        constructor_refs = dict(cur.fetchall())
        cur.execute("SELECT ref, circuit_id FROM circuits")
        circuit_refs = dict(cur.fetchall())
    return EntityRows(
        seasons=seasons,
        races=races,
        circuits=circuits,
        drivers=drivers,
        constructors=constructors,
        driver_refs=driver_refs,
        constructor_refs=constructor_refs,
        circuit_refs=circuit_refs,
    )
