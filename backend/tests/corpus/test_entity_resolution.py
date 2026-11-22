"""Entity resolution on the real data: 30 labelled questions (F3.4).

Opt-in and read-only, like test_search_quality.py:

    CORPUS_DATABASE_URL=postgresql://…/apexgpt uv run pytest -m corpus

Each question lists the best guess for every name it contains, in order, as
(kind, ref). The set covers nicknames, ambiguous surnames with and without a
season, everyday words ("pace", "speed", "era", "March"), lowercase questions,
teams named after drivers, and circuit/driver clashes. The first 21 were used to
tune the ranking; the last 9 were added afterwards and passed unchanged.
"""

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.config import normalise_database_url
from app.retrieval.entities import EntityResolver, load_entity_index

pytestmark = pytest.mark.corpus

_URL = os.environ.get("CORPUS_DATABASE_URL")
if not _URL:
    pytest.skip("CORPUS_DATABASE_URL not set", allow_module_level=True)

# question -> expected best guesses, in order: (kind, ref)
EVAL = {
    "How many wins did Schumi have at Monza?": [
        ("driver", "michael_schumacher"),
        ("circuit", "monza"),
    ],
    "Hamilton vs Verstappen at Abu Dhabi 2021": [
        ("driver", "hamilton"),
        ("driver", "max_verstappen"),
        ("circuit", "yas_marina"),
    ],
    "Did Hill win the title in 1996?": [("driver", "damon_hill")],
    "Graham Hill's Monaco wins": [("driver", "hill"), ("circuit", "monaco")],
    "Checo's podiums with Red Bull": [("driver", "perez"), ("constructor", "red_bull")],
    "Kimi at Ferrari in 2007": [("driver", "raikkonen"), ("constructor", "ferrari")],
    "Senna vs Prost at Suzuka": [
        ("driver", "senna"),
        ("driver", "prost"),
        ("circuit", "suzuka"),
    ],
    "What was the pace of Mercedes in the hybrid era?": [("constructor", "mercedes")],
    "Who was the fastest driver in 1950?": [],
    "Top speed record at Monza": [("circuit", "monza")],
    "Button and Barrichello at Brawn in 2009": [
        ("driver", "button"),
        ("driver", "barrichello"),
        ("constructor", "brawn"),
    ],
    "Jacques Villeneuve 1997 title": [("driver", "villeneuve")],
    "Gilles Villeneuve fatal crash at Zolder": [
        ("driver", "gilles_villeneuve"),
        ("circuit", "zolder"),
    ],
    "McLaren dominance in 1988": [("constructor", "mclaren")],
    "lewis hamilton wins at silverstone": [
        ("driver", "hamilton"),
        ("circuit", "silverstone"),
    ],
    "the professor and the iceman": [("driver", "prost"), ("driver", "raikkonen")],
    "Force India points in 2016": [("constructor", "force_india")],
    "In March 1990, who led the championship?": [],
    "How did Hunt beat Lauda in 1976": [("driver", "hunt"), ("driver", "lauda")],
    "Schumacher in 2022": [("driver", "mick_schumacher")],
    "Races at Spa in the rain": [("circuit", "spa")],
    "Fittipaldi's 1972 title": [("driver", "emerson_fittipaldi")],
    "Brabham BT46 fan car": [("constructor", "brabham")],
    "Prost Grand Prix team in 1998": [("constructor", "prost")],
    "Michael Schumacher Ferrari Imola 2006": [
        ("driver", "michael_schumacher"),
        ("constructor", "ferrari"),
        ("circuit", "imola"),
    ],
    "Who won at Interlagos in 2008?": [("circuit", "interlagos")],
    "Singapore night race crash 2008": [("circuit", "marina_bay")],
    "Nelson Piquet at Jacarepagua": [("driver", "piquet"), ("circuit", "jacarepagua")],
    "Hockenheim 2000 Barrichello first win": [
        ("circuit", "hockenheimring"),
        ("driver", "barrichello"),
    ],
    "speed trap data and driver pace at Spa-Francorchamps": [("circuit", "spa")],
}


@pytest.fixture(scope="module")
def resolver() -> Iterator[EntityResolver]:
    engine = create_engine(
        normalise_database_url(_URL), connect_args={"prepare_threshold": None}
    )
    with Session(engine) as session:
        index = load_entity_index(session)
        session.rollback()
    yield EntityResolver(lambda: index)
    engine.dispose()


@pytest.mark.parametrize(("question", "expected"), EVAL.items(), ids=list(EVAL))
def test_best_guesses(
    resolver: EntityResolver, question: str, expected: list[tuple[str, str]]
) -> None:
    mentions = resolver.resolve(question).mentions
    found = [(m.best.entity.kind, m.best.entity.ref) for m in mentions]

    assert found == expected, [
        (m.text, [(c.entity.kind, c.entity.ref) for c in m.candidates])
        for m in mentions
    ]


def test_every_curated_circuit_name_points_at_a_real_circuit(
    resolver: EntityResolver,
) -> None:
    from app.retrieval.entities import CIRCUIT_NICKNAMES

    index = resolver.index()
    for alias, ref in CIRCUIT_NICKNAMES.items():
        refs = [e.ref for e, _ in index.aliases.get(alias, ())]
        assert ref in refs, alias
