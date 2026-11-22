"""Entity resolution with a hand-built index (no database)."""

from pathlib import Path

import pytest
from sqlalchemy.exc import OperationalError

from app.retrieval import entities as entities_module
from app.retrieval.entities import (
    COMMON_WORDS,
    MAX_CANDIDATES,
    NEVER_ALONE,
    Entity,
    EntityIndex,
    EntityIndexUnavailableError,
    EntityResolver,
    circuit_aliases,
)
from app.retrieval.errors import SearchError
from app.retrieval.normalise import normalise_alias

INGESTION_ALIASES = (
    Path(__file__).resolve().parents[3] / "ingestion" / "structured" / "aliases.py"
)


def driver(
    i: int, ref: str, name: str, seasons=(), wins: int = 0, races: int = 10
) -> Entity:
    return Entity("driver", i, ref, name, frozenset(seasons), wins, races)


def team(
    i: int, ref: str, name: str, seasons=(), wins: int = 0, races: int = 10
) -> Entity:
    return Entity("constructor", i, ref, name, frozenset(seasons), wins, races)


def circuit(i: int, ref: str, name: str, seasons=(), races: int = 10) -> Entity:
    return Entity("circuit", i, ref, name, frozenset(seasons), 0, races)


MICHAEL = driver(
    30, "michael_schumacher", "Michael Schumacher", range(1991, 2013), 91, 308
)
RALF = driver(31, "ralf_schumacher", "Ralf Schumacher", range(1997, 2008), 6, 180)
MICK = driver(32, "mick_schumacher", "Mick Schumacher", (2021, 2022), 0, 44)
DAMON = driver(40, "damon_hill", "Damon Hill", range(1992, 2000), 22, 116)
GRAHAM = driver(41, "hill", "Graham Hill", range(1958, 1976), 14, 177)
ALAIN = driver(50, "prost", "Alain Prost", range(1980, 1994), 51, 202)
SPEED = driver(60, "speed", "Scott Speed", (2006, 2007), 0, 28)
PACE = driver(61, "pace", "Carlos Pace", range(1972, 1978), 1, 73)
BRUCE = driver(70, "mclaren_bruce", "Bruce McLaren", range(1959, 1971), 4, 101)
PROST_GP = team(5, "prost", "Prost", range(1997, 2002), 0, 83)
MCLAREN = team(1, "mclaren", "McLaren", range(1966, 2026), 183, 960)
MARCH = team(9, "march", "March", range(1970, 1993), 3, 230)
FORCE_INDIA = team(10, "force_india", "Force India", range(2008, 2019), 0, 200)
MONZA = circuit(7, "monza", "Autodromo Nazionale di Monza", range(1950, 2026), 75)
MONTREAL = circuit(44, "villeneuve", "Circuit Gilles Villeneuve", range(1978, 2026), 44)
GILLES = driver(80, "gilles_villeneuve", "Gilles Villeneuve", range(1977, 1983), 6, 67)
RED_BULL = team(9_1, "red_bull", "Red Bull", range(2005, 2026), 130, 400)
RED_BULL_RING = circuit(70, "red_bull_ring", "Red Bull Ring", range(2014, 2026), 12)
KIMI = driver(90, "raikkonen", "Kimi Räikkönen", range(2001, 2022), 21, 352)
ANTONELLI = driver(91, "antonelli", "Andrea Kimi Antonelli", (2025,), 0, 24)
JACQUES = driver(81, "villeneuve", "Jacques Villeneuve", range(1996, 2007), 11, 165)

ENTRIES = [
    ("Michael Schumacher", MICHAEL, "name"),
    ("Schumacher", MICHAEL, "surname"),
    ("Schumi", MICHAEL, "nickname"),
    ("Ralf Schumacher", RALF, "name"),
    ("Schumacher", RALF, "surname"),
    ("Mick Schumacher", MICK, "name"),
    ("Schumacher", MICK, "surname"),
    ("Damon Hill", DAMON, "name"),
    ("Hill", DAMON, "surname"),
    ("Graham Hill", GRAHAM, "name"),
    ("Hill", GRAHAM, "surname"),
    ("Alain Prost", ALAIN, "name"),
    ("Prost", ALAIN, "surname"),
    ("the professor", ALAIN, "nickname"),
    ("Prost", PROST_GP, "name"),
    ("Scott Speed", SPEED, "name"),
    ("Speed", SPEED, "surname"),
    ("Carlos Pace", PACE, "name"),
    ("Pace", PACE, "surname"),
    ("Bruce McLaren", BRUCE, "name"),
    ("McLaren", BRUCE, "surname"),
    ("McLaren", MCLAREN, "name"),
    ("March", MARCH, "name"),
    ("Force India", FORCE_INDIA, "name"),
    ("Gilles Villeneuve", GILLES, "name"),
    ("Villeneuve", GILLES, "surname"),
    ("Jacques Villeneuve", JACQUES, "name"),
    ("Villeneuve", JACQUES, "surname"),
    ("Red Bull", RED_BULL, "name"),
    ("Red Bull Ring", RED_BULL_RING, "circuit"),
    ("Kimi Räikkönen", KIMI, "name"),
    ("Kimi", KIMI, "nickname"),
    ("Kimi", ANTONELLI, "nickname"),
    ("Kimi Antonelli", ANTONELLI, "nickname"),
    *[
        (alias, MONZA, "circuit")
        for alias in circuit_aliases("monza", MONZA.name, "Monza")
    ],
    *[
        (alias, MONTREAL, "circuit")
        for alias in circuit_aliases("villeneuve", MONTREAL.name, "Montreal")
    ],
]
INDEX = EntityIndex.build(ENTRIES)


def resolver() -> EntityResolver:
    return EntityResolver(lambda: INDEX)


def best(question: str) -> list[str]:
    return [m.best.entity.ref for m in resolver().resolve(question).mentions]


# --- normalisation ---


def test_normalise_matches_the_ingestion_loader() -> None:
    if not INGESTION_ALIASES.exists():  # e.g. inside the backend Docker image
        pytest.skip("ingestion/ is not available")
    source = INGESTION_ALIASES.read_text()
    # Compare the function itself without importing ingestion's dependencies.
    start = source.index("# Letters NFKD does not decompose")
    end = source.index("@dataclass(frozen=True)\nclass LineageSeed")
    namespace: dict = {}
    exec("import re\nimport unicodedata\n" + source[start:end], namespace)  # noqa: S102
    samples = [
        "Sergio Pérez", "O'Ward", "Räikkönen", "Nürburgring", "Hülkenberg", "Øystein",
        "Æsir", "Großglockner", "Łukasz", "Đorđe", "  Multi   21 ", "São Paulo",
        "Kimi Räikkönen's", "MONTMELÓ", "ı dotless", "x²", "Spa-Francorchamps", "",
    ]  # fmt: skip
    for sample in samples:
        assert normalise_alias(sample) == namespace["normalise_alias"](sample), sample


@pytest.mark.parametrize(
    ("raw", "normalised"),
    [
        ("Sergio Pérez", "sergio perez"),
        ("O'Ward", "o ward"),
        ("Räikkönen", "raikkonen"),
    ],
)
def test_normalise_examples(raw: str, normalised: str) -> None:
    assert normalise_alias(raw) == normalised


# --- circuit aliases ---


@pytest.mark.parametrize(
    ("ref", "name", "locality", "expected"),
    [
        ("spa", "Circuit de Spa-Francorchamps", "Spa", {"spa", "spa francorchamps"}),
        ("monza", "Autodromo Nazionale di Monza", "Monza", {"monza"}),
        (
            "albert_park",
            "Albert Park Grand Prix Circuit",
            "Melbourne",
            {"albert park", "melbourne"},
        ),
        ("americas", "Circuit of the Americas", "Austin", {"americas", "austin"}),
        (
            "imola",
            "Autodromo Enzo e Dino Ferrari",
            "Imola",
            {"imola", "enzo e dino ferrari"},
        ),
        ("red_bull_ring", "Red Bull Ring", "Spielberg", {"red bull ring", "spielberg"}),
        ("ain-diab", "Ain Diab", "Casablanca", {"ain diab", "casablanca"}),
    ],
)
def test_circuit_aliases(
    ref: str, name: str, locality: str, expected: set[str]
) -> None:
    aliases = circuit_aliases(ref, name, locality)

    assert expected <= aliases
    assert normalise_alias(name) in aliases  # the full name too


def test_circuit_names_are_never_stripped_to_nothing_or_to_a_team() -> None:
    assert "ferrari" not in circuit_aliases(
        "imola", "Autodromo Enzo e Dino Ferrari", None
    )
    assert circuit_aliases("x", "Circuit", None) == {"x", "circuit"}


# --- matching ---


def test_names_nicknames_and_circuits_are_found_in_order() -> None:
    resolution = resolver().resolve("How many wins did Schumi have at Monza?")

    schumi, monza = resolution.mentions
    assert (schumi.text, schumi.alias, schumi.best.match) == (
        "Schumi",
        "schumi",
        "nickname",
    )
    assert schumi.best.entity == MICHAEL and not schumi.ambiguous
    assert (monza.text, monza.best.entity, monza.best.match) == (
        "Monza",
        MONZA,
        "circuit",
    )
    assert resolution.question[monza.start : monza.end] == "Monza"


def test_the_longest_alias_wins() -> None:
    (mention,) = resolver().resolve("Michael Schumacher's last title").mentions

    assert mention.text == "Michael Schumacher" and mention.best.match == "name"
    assert mention.candidates == (mention.best,)  # not ambiguous


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Red Bull Ring lap record", ["red_bull_ring"]),  # not the team + "Ring"
        ("Red Bull won at the Red Bull Ring", ["red_bull", "red_bull_ring"]),
        ("Kimi Räikkönen in 2007", ["raikkonen"]),
        ("Kimi Antonelli in 2025", ["antonelli"]),
    ],
)
def test_a_longer_alias_beats_a_shorter_one_inside_it(
    question: str, expected: list[str]
) -> None:
    assert best(question) == expected


def test_kimi_alone_is_ambiguous_and_the_season_decides() -> None:
    (mention,) = resolver().resolve("Kimi in 2025").mentions

    assert mention.ambiguous and mention.best.entity == ANTONELLI
    assert resolver().resolve("Kimi in 2007").mentions[0].best.entity == KIMI


def test_multi_word_nicknames_and_case_insensitive_matching() -> None:
    assert best("the PROFESSOR at monza") == ["prost", "monza"]


def test_accents_and_punctuation_are_normalised() -> None:
    index = EntityIndex.build(
        [("Kimi Räikkönen", driver(1, "raikkonen", "Kimi Räikkönen"), "name")]
    )

    (mention,) = (
        EntityResolver(lambda: index).resolve("Did kimi raikkonen's car fail?").mentions
    )
    assert mention.text == "kimi raikkonen" and mention.best.entity.ref == "raikkonen"


def test_ambiguous_surnames_list_every_candidate_by_prominence() -> None:
    (mention,) = resolver().resolve("Schumacher's best season").mentions

    assert mention.ambiguous
    assert [c.entity for c in mention.candidates] == [MICHAEL, RALF, MICK]
    assert all(c.match == "surname" and not c.active for c in mention.candidates)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("Schumacher in 2022", "mick_schumacher"),
        ("Schumacher in 1999", "michael_schumacher"),  # Michael and Ralf: wins decide
        ("Hill in 1996", "damon_hill"),
        ("Hill in 1962", "hill"),
        ("Villeneuve in 1997", "villeneuve"),  # Jacques
        ("Villeneuve in 1980", "gilles_villeneuve"),
    ],
)
def test_a_season_in_the_question_puts_active_entities_first(
    question: str, expected: str
) -> None:
    mention = resolver().resolve(question).mentions[0]

    assert mention.best.entity.ref == expected
    assert mention.best.active


def test_a_team_name_and_a_surname_rank_equally_so_prominence_decides() -> None:
    (mclaren,) = resolver().resolve("McLaren").mentions
    (prost,) = resolver().resolve("Prost").mentions

    assert [c.entity for c in mclaren.candidates] == [MCLAREN, BRUCE]  # 183 v 4 wins
    assert [c.entity for c in prost.candidates] == [ALAIN, PROST_GP]  # 51 v 0 wins


def test_a_driver_surname_outranks_a_circuit_of_the_same_name() -> None:
    (mention,) = resolver().resolve("Villeneuve").mentions

    assert [c.entity.kind for c in mention.candidates] == [
        "driver",
        "driver",
        "circuit",
    ]
    assert MONTREAL in [c.entity for c in mention.candidates]


@pytest.mark.parametrize(
    "question",
    [
        "What was the pace of Mercedes?",
        "top speed at the end of the straight",
        "In March 1990 who led?",
        "March 1990",  # capitalised month
        "May 2005",
    ],
)
def test_everyday_words_are_not_names(question: str) -> None:
    refs = best(question)

    assert "pace" not in refs and "speed" not in refs and "march" not in refs


def test_capitalised_everyday_words_are_names() -> None:
    assert best("Pace and Speed") == ["pace", "speed"]


def test_multi_word_aliases_with_everyday_words_always_match() -> None:
    assert best("force india points") == ["force_india"]
    assert best("scott speed in 2006") == ["speed"]


def test_lowercase_questions_still_find_unambiguous_names() -> None:
    assert best("schumi vs the professor at monza") == [
        "michael_schumacher",
        "prost",
        "monza",
    ]


def test_never_alone_and_common_words_are_lowercase_aliases() -> None:
    for word in COMMON_WORDS | NEVER_ALONE:
        assert normalise_alias(word) == word and " " not in word


def test_candidates_are_capped() -> None:
    many = [
        ("Taylor", driver(i, f"taylor_{i}", f"Driver {i} Taylor", wins=i), "surname")
        for i in range(9)
    ]
    index = EntityIndex.build(many)

    (mention,) = EntityResolver(lambda: index).resolve("Taylor").mentions
    assert len(mention.candidates) == MAX_CANDIDATES
    assert mention.best.entity.wins == 8


def test_an_entity_keeps_its_strongest_match_for_an_alias() -> None:
    kimi = driver(1, "raikkonen", "Kimi Räikkönen")
    index = EntityIndex.build([("kimi", kimi, "surname"), ("Kimi", kimi, "nickname")])

    assert index.aliases["kimi"] == ((kimi, "nickname"),)


def test_resolution_best_by_kind_and_seasons() -> None:
    resolution = resolver().resolve("Did Schumi beat Hill at Monza in 1994 and 1995?")

    assert resolution.seasons == (1994, 1995)
    assert resolution.best("driver") == [MICHAEL, DAMON]
    assert resolution.best("circuit") == [MONZA]
    assert resolution.best("constructor") == []


def test_no_names_means_no_mentions() -> None:
    assert resolver().resolve("Who won the most races?").mentions == ()


@pytest.mark.parametrize("bad", ["", "   ", "x" * 501])
def test_bad_questions_are_rejected_before_loading(bad: str) -> None:
    calls = []

    with pytest.raises(ValueError):
        EntityResolver(lambda: calls.append(1) or INDEX).resolve(bad)
    assert calls == []


# --- loading, caching and failures ---


def test_index_is_loaded_lazily_once_and_reloaded_after_the_ttl() -> None:
    now = [0.0]
    loads = []

    def load() -> EntityIndex:
        loads.append(now[0])
        return INDEX

    resolver_ = EntityResolver(load, ttl_seconds=100, clock=lambda: now[0])
    assert loads == []

    resolver_.resolve("Schumi")
    now[0] = 50
    resolver_.resolve("Schumi")
    now[0] = 151
    resolver_.resolve("Schumi")

    assert loads == [0.0, 151]


def test_load_failure_without_an_index_is_a_safe_search_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken() -> EntityIndex:
        raise OperationalError("SELECT", {}, Exception("db.internal password=x"))

    with pytest.raises(EntityIndexUnavailableError, match="unavailable") as info:
        EntityResolver(broken).resolve("Schumi")

    assert isinstance(info.value, SearchError) and info.value.__cause__ is None
    assert "password" not in caplog.text and "OperationalError" in caplog.text


def test_a_failed_reload_keeps_serving_the_previous_index(
    caplog: pytest.LogCaptureFixture,
) -> None:
    now = [0.0]
    outcomes: list = [INDEX, OperationalError("SELECT", {}, Exception("down"))]

    def load() -> EntityIndex:
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    resolver_ = EntityResolver(load, ttl_seconds=10, clock=lambda: now[0])
    resolver_.resolve("Schumi")
    now[0] = 20

    assert best_refs(resolver_, "Schumi") == ["michael_schumacher"]
    assert "Entity index failed to load" in caplog.text


def best_refs(resolver_: EntityResolver, question: str) -> list[str]:
    return [m.best.entity.ref for m in resolver_.resolve(question).mentions]


def test_entity_properties() -> None:
    assert (MICK.first_season, MICK.last_season) == (2021, 2022)
    empty = driver(99, "x", "Nobody")
    assert (empty.first_season, empty.last_season) == (None, None)
    assert "seasons" not in repr(MICK)


# --- CLI ---


def test_cli_prints_the_candidates(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from tests.conftest import make_settings

    monkeypatch.setattr("app.core.config.get_settings", lambda: make_settings())
    monkeypatch.setattr(entities_module, "load_entity_index", lambda session: INDEX)

    assert entities_module.run(["Hill at Monza in 1996"]) == 0

    out = capsys.readouterr().out
    assert "2 names found (seasons in question: 1996)" in out
    assert '"Hill"  (ambiguous)' in out
    assert (
        "1. driver Damon Hill [damon_hill, id 40] 1992–1999, 22 wins, 116 races (surname, active)"
        in out
    )
    assert (
        "circuit Autodromo Nazionale di Monza [monza, id 7] 1950–2025, 75 races hosted"
        in out
    )


def test_cli_bad_question_exits_2(capsys) -> None:
    assert entities_module.run(["   "]) == 2
    assert "must not be empty" in capsys.readouterr().err


def test_cli_load_failure_exits_1(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    from tests.conftest import make_settings

    def broken(session):
        raise OperationalError("SELECT", {}, Exception("down"))

    monkeypatch.setattr("app.core.config.get_settings", lambda: make_settings())
    monkeypatch.setattr(entities_module, "load_entity_index", broken)

    assert entities_module.run(["Schumi"]) == 1
    assert "Name lookup is unavailable right now" in capsys.readouterr().err
