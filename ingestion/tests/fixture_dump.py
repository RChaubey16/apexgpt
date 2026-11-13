"""A tiny Jolpica-style dump covering the edge cases found in the real one.

Rounds (season):
- 1 (2021 R1): Q1/Q2/Q3, sprint, race. Verstappen wins; Hamilton retires
  (unclassified, status code only, fastest-lap rank 0). One pit stop.
- 2 (2021 R2): cancelled -> skipped.
- 3 (2021 R3): no entries yet (future race) -> skipped.
- 4 (2020 R1): two QB sessions; a shared drive (Hamilton in two cars, and two
  drivers sharing first place and its points); a float-artefact points value.
- 5 (2027 R1): outside the default season range -> ignored with its entities.
"""

import copy
import csv
import io
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from structured.dump import REQUIRED_COLUMNS, Row, check_columns

Tables = dict[str, list[dict[str, str]]]


def _rows(header: str, *values: str) -> list[dict[str, str]]:
    cols = header.split(",")
    return [dict(zip(cols, v.split(","), strict=True)) for v in values]


BASE: Tables = {
    "season": _rows(
        "id,year,wikipedia,api_id",
        "1,2020,https://en.wikipedia.org/wiki/2020_Formula_One_World_Championship,s1",
        "2,2021,https://en.wikipedia.org/wiki/2021_Formula_One_World_Championship,s2",
        "3,2027,,s3",
    ),
    "circuit": _rows(
        "id,reference,name,locality,country,latitude,longitude,altitude,wikipedia,country_code",
        "1,bahrain,Bahrain International Circuit,Sakhir,Bahrain,26.0325,50.5106,7,https://en.wikipedia.org/wiki/Bahrain_International_Circuit,BHR",
        "2,red_bull_ring,Red Bull Ring,Spielberg,Austria,47.2197,14.7647,678,,AUT",
        "3,future_track,Future Track,Somewhere,Nowhere,0,0,0,,XXX",
    ),
    "driver": _rows(
        "id,reference,abbreviation,permanent_car_number,forename,surname,date_of_birth,nationality,wikipedia,api_id",
        "1,hamilton,HAM,44,Lewis,Hamilton,1985-01-07,British,http://en.wikipedia.org/wiki/Lewis_Hamilton,d1",
        "2,max_verstappen,VER,33,Max,Verstappen,1997-09-30,Dutch,http://en.wikipedia.org/wiki/Max_Verstappen,d2",
        "3,unused,,,Never,Raced,,,,d3",
        "4,future,FUT,,Future,Driver,,,,d4",
    ),
    "team": _rows(
        "id,reference,name,nationality,wikipedia,base_team_id",
        "1,mercedes,Mercedes,German,http://en.wikipedia.org/wiki/Mercedes-Benz_in_Formula_One,",
        "2,red_bull,Red Bull,Austrian,http://en.wikipedia.org/wiki/Red_Bull_Racing,",
        "3,unused,Unused,,,",
    ),
    "round": _rows(
        "id,season_id,number,name,circuit_id,date,is_cancelled,wikipedia,race_number",
        "1,2,1,Bahrain Grand Prix,1,2021-03-28,f,https://en.wikipedia.org/wiki/2021_Bahrain_Grand_Prix,1",
        "2,2,2,Cancelled Grand Prix,1,2021-04-04,t,,",
        "3,2,3,Future Grand Prix,1,2021-12-12,f,,3",
        "4,1,1,Austrian Grand Prix,2,2020-07-05,f,,1",
        "5,3,1,Season Opener,3,2027-03-01,f,,1",
    ),
    "session": _rows(
        "id,round_id,number,type,is_cancelled,timestamp",
        "10,1,1,Q1,f,",
        "11,1,2,Q2,f,",
        "12,1,3,Q3,f,",
        "13,1,4,SR,f,",
        "14,1,5,R,f,",
        "15,1,6,FP1,f,",
        "19,3,1,R,f,",
        "20,4,1,QB,f,",
        "21,4,2,QB,f,",
        "22,4,3,R,f,",
        "30,5,1,R,f,",
    ),
    "teamdriver": _rows(
        "id,driver_id,team_id,season_id,role",
        "1,1,1,2,",
        "2,2,2,2,",
        "3,1,2,1,",
        "4,4,1,3,",
        "5,1,1,1,",
        "6,2,2,1,",
    ),
    "roundentry": _rows(
        "id,round_id,team_driver_id,car_number,api_id",
        "1,1,1,44,re1",
        "2,1,2,33,re2",
        "3,4,5,44,re3",
        "4,4,3,5,re4",
        "5,4,6,33,re5",
        "6,5,4,1,re6",
    ),
    "sessionentry": _rows(
        "id,session_id,round_entry_id,position,is_classified,status,detail,points,grid,time,fastest_lap_rank,laps_completed",
        # 2021 R1 race
        "100,14,2,1,t,0,Finished,25,2,01:32:03.897,1,56",
        "101,14,1,2,f,11,,0,1,,0,10",
        # sprint
        "110,13,1,1,t,0,Finished,3,1,00:25:38.426,,17",
        "111,13,2,2,t,0,Finished,2,2,00:25:39.100,,17",
        # Q1/Q2/Q3
        "120,10,1,2,,,,,,,,",
        "121,10,2,1,,,,,,,,",
        "122,11,1,1,,,,,,,,",
        "123,11,2,2,,,,,,,,",
        "124,12,2,1,,,,,,,,",
        "125,12,1,2,,,,,,,,",
        # practice: ignored
        "126,15,1,1,,,,,,,,",
        # 2020 R1: two QB sessions, Hamilton also in car 5
        "130,20,3,1,,,,,,,,",
        "131,20,5,2,,,,,,,,",
        "134,20,4,3,,,,,,,,",
        "132,21,3,2,,,,,,,,",
        "133,21,5,1,,,,,,,,",
        "140,22,3,1,t,0,Finished,4.5,1,01:30:55.739,2,71",
        "141,22,5,1,t,0,Finished,4.5,2,01:30:55.739,1,71",
        "142,22,4,3,t,1,+1 Lap,1.1400000000000001,3,,,70",
        # 2027: out of range
        "150,30,6,1,t,0,Finished,25,1,01:30:00.000,1,50",
    ),
    "lap": _rows(
        "id,session_entry_id,number,time,is_entry_fastest_lap,is_deleted,position",
        "1,100,44,00:01:32.090,t,f,",
        "2,101,,00:01:40.000,t,t,",  # deleted: ignored
        "3,120,,00:01:31.000,t,f,",
        "4,121,,00:01:30.500,t,f,",
        "5,122,,00:01:30.200,t,f,",
        "6,123,,00:01:30.300,t,f,",
        "7,124,,00:01:29.385,t,f,",
        "8,125,,00:01:29.600,t,f,",
        "9,130,,00:01:03.000,t,f,",
        "10,132,,00:01:02.939,t,f,",
        "11,131,,00:01:03.500,t,f,",
        "12,133,,00:01:02.900,t,f,",
        "13,141,67,00:01:07.475,t,f,",
        "900,100,20,00:01:50.000,f,f,",
    ),
    "pitstop": _rows(
        "id,session_entry_id,number,lap_id,local_timestamp,duration",
        "1,100,1,900,18:35:12,00:00:22.500",
    ),
    "driverchampionship": _rows(
        "id,driver_id,round_id,points,position,win_count,is_eligible,adjustment_type,season_id,year",
        "1,2,1,25,1,1,t,0,,2021",
        "2,1,1,3,2,0,t,0,2,2021",
        "3,1,4,4.5,,1,t,101,1,2020",
        "4,2,4,4.5,,1,f,0,1,2020",
        "5,1,,0,1,0,t,0,,2021",  # per-session row without a round: ignored
        "6,4,5,25,1,1,t,0,3,2027",
    ),
    "teamchampionship": _rows(
        "id,team_id,round_id,points,position,win_count,is_eligible,adjustment_type,season_id,year",
        "1,2,1,27,1,1,t,0,,2021",
        "2,1,1,3,2,0,t,0,2,2021",
    ),
}


def tables() -> Tables:
    """A fresh, mutable copy of the fixture tables."""
    return copy.deepcopy(BASE)


class FakeSource:
    """In-memory TableSource with the same column checks as the zip reader."""

    def __init__(self, data: Tables | None = None) -> None:
        self.data = data if data is not None else tables()

    def rows(self, table: str) -> Iterator[Row]:
        rows = self.data[table]
        check_columns(table, list(rows[0]) if rows else list(REQUIRED_COLUMNS[table]))
        yield from rows


def write_zip(path: Path, data: Tables | None = None, **members: Any) -> Path:
    """Write the fixture as a Jolpica-style dump zip (extra `members` override files)."""
    data = data if data is not None else tables()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for table, rows in data.items():
            buf = io.StringIO()
            writer = csv.DictWriter(buf, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
            zf.writestr(f"formula_one_{table}.csv", buf.getvalue())
        for name, content in members.items():
            zf.writestr(name, content)
    return path
