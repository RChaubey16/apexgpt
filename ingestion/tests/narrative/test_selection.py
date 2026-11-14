import pytest

from narrative.errors import SelectionError
from narrative.selection import (
    MAJOR_MIN_SEASONS,
    NOTABLE_MIN_STARTS,
    CircuitRow,
    ConstructorRow,
    Depth,
    DriverRow,
    EntityRows,
    Kind,
    RaceRow,
    SeasonRow,
    Selected,
    TitleOverride,
    is_major_constructor,
    is_notable_driver,
    merge,
    merge_depth,
    resolve_selection,
    select_articles,
    summarise,
    title_from_url,
)
from narrative.topics import Group, Topic
from narrative.wiki import WikiClient
from tests.narrative.fake_wiki import FakeWiki

W = "https://en.wikipedia.org/wiki/"


# --- URLs -> titles ---


@pytest.mark.parametrize(
    ("url", "title", "anchor"),
    [
        (W + "Ayrton_Senna", "Ayrton Senna", None),
        ("http://en.wikipedia.org/wiki/Lewis_Hamilton", "Lewis Hamilton", None),
        (W + "2021_S%C3%A3o_Paulo_Grand_Prix", "2021 São Paulo Grand Prix", None),
        (W + "2022_São_Paulo_Grand_Prix", "2022 São Paulo Grand Prix", None),
        (W + "Kimi_R%C3%A4ikk%C3%B6nen", "Kimi Räikkönen", None),
        (W + "Las_Vegas_Grand_Prix#Circuit", "Las Vegas Grand Prix", "Circuit"),
        (
            W + "Circuit_de_la_Sarthe#Bugatti_Circuit",
            "Circuit de la Sarthe",
            "Bugatti Circuit",
        ),
        (W + "LDS_(automobile)", "LDS (automobile)", None),
        (W + "Formula_1:_Drive_to_Survive", "Formula 1: Drive to Survive", None),
        ("  " + W + "McLaren  ", "McLaren", None),
        ("https://EN.wikipedia.org/wiki/McLaren", "McLaren", None),
    ],
)
def test_title_from_url(url: str, title: str, anchor: str | None) -> None:
    assert title_from_url(url) == (title, anchor)


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        (
            "http://en.wikipedia.org/wiki/Talk:1963_Mexican_Grand_Prix#Who",
            "Talk page",
        ),
        (W + "File:Senna.jpg", "File page"),
        (W + "Category:Formula_One_drivers", "Category page"),
        (W + "user_talk:Someone", "User talk page"),
        ("https://de.wikipedia.org/wiki/Ayrton_Senna", "English Wikipedia"),
        ("https://en.wikipedia.org/w/index.php?title=Senna", "English Wikipedia"),
        (W + "Senna?action=edit", "English Wikipedia"),
        ("ftp://en.wikipedia.org/wiki/Senna", "English Wikipedia"),
        ("https://en.wikipedia.org.evil.example/wiki/Senna", "English Wikipedia"),
        ("not a url", "English Wikipedia"),
        (W, "empty"),
        (W + "A%7CB", "forbids"),
    ],
)
def test_title_from_url_rejects_non_articles(url: str, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        title_from_url(url)


# --- depth and merging ---


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        (Depth.LEAD, Depth.LEAD, Depth.LEAD),
        (Depth.LEAD, Depth.RACE, Depth.RACE),
        (Depth.CIRCUIT, Depth.LEAD, Depth.CIRCUIT),
        (Depth.RACE, Depth.FULL, Depth.FULL),
        (Depth.LEAD, Depth.FULL, Depth.FULL),
        (Depth.RACE, Depth.CIRCUIT, Depth.FULL),
        (Depth.RACE, Depth.RACE, Depth.RACE),
    ],
)
def test_merge_depth(a: Depth, b: Depth, expected: Depth) -> None:
    assert merge_depth(a, b) == expected
    assert merge_depth(b, a) == expected


def test_merge_unions_ids_and_keeps_agreeing_fields() -> None:
    race = Selected(
        title="1989 Japanese Grand Prix",
        kinds=(Kind.RACE,),
        depth=Depth.RACE,
        season=1989,
        race_id=480,
        circuit_id=22,
    )
    topic = Selected(
        title="1989 Japanese Grand Prix",
        kinds=(Kind.TOPIC,),
        depth=Depth.FULL,
        season=1989,
        driver_ids=(117, 102),
        topic="iconic_race",
    )

    merged = merge(race, topic)

    assert merged.kinds == (Kind.RACE, Kind.TOPIC)
    assert merged.depth == Depth.FULL
    assert (merged.season, merged.race_id, merged.circuit_id) == (1989, 480, 22)
    assert merged.driver_ids == (102, 117)
    assert merged.topic == "iconic_race"


def test_merge_drops_conflicting_single_values() -> None:
    a = Selected(title="X", kinds=(Kind.TOPIC,), depth=Depth.FULL, season=1988)
    b = Selected(
        title="X", kinds=(Kind.DRIVER,), depth=Depth.LEAD, season=1989, anchor="A"
    )

    merged = merge(a, b)

    assert merged.season is None
    assert merged.anchor == "A"
    assert merged.kinds == (Kind.DRIVER, Kind.TOPIC)


def test_merge_refuses_two_topic_groups() -> None:
    a = Selected(title="X", kinds=(Kind.TOPIC,), depth=Depth.FULL, topic="rivalry")
    b = Selected(title="X", kinds=(Kind.TOPIC,), depth=Depth.FULL, topic="safety")
    with pytest.raises(SelectionError, match="two topic groups"):
        merge(a, b)


# --- rules ---


@pytest.mark.parametrize(
    ("row", "notable"),
    [
        (DriverRow(1, "a", None), False),
        (DriverRow(1, "a", None, championships=1), True),
        (DriverRow(1, "a", None, wins=1), True),
        (DriverRow(1, "a", None, podiums=1), True),
        (DriverRow(1, "a", None, starts=NOTABLE_MIN_STARTS), True),
        (DriverRow(1, "a", None, starts=NOTABLE_MIN_STARTS - 1), False),
    ],
)
def test_notable_driver(row: DriverRow, notable: bool) -> None:
    assert is_notable_driver(row) is notable


def _team(cid: int, seasons: range | tuple = (), **kw) -> ConstructorRow:
    return ConstructorRow(cid, f"team{cid}", W + "Team", frozenset(seasons), **kw)


@pytest.mark.parametrize(
    ("rows", "major"),
    [
        ([_team(1, range(1960, 1960 + MAJOR_MIN_SEASONS - 1))], False),
        ([_team(1, range(1960, 1960 + MAJOR_MIN_SEASONS))], True),
        ([_team(1, (1960,), wins=1)], True),
        ([_team(1, (1960,), champion=True)], True),
        # Seasons are counted over every row sharing the article...
        ([_team(1, (1960, 1961, 1962)), _team(2, (1962, 1963, 1964))], True),
        # ...without counting a season twice.
        ([_team(1, (1960, 1961, 1962)), _team(2, (1961, 1962, 1963))], False),
    ],
)
def test_major_constructor(rows: list[ConstructorRow], major: bool) -> None:
    assert is_major_constructor(rows) is major


def _rows() -> EntityRows:
    return EntityRows(
        seasons=[
            SeasonRow(1989, W + "1989_Formula_One_season"),
            SeasonRow(1990, None),
        ],
        races=[
            RaceRow(
                480, 1989, 22, "Japanese Grand Prix", W + "1989_Japanese_Grand_Prix"
            ),
            RaceRow(
                481, 1989, 29, "Australian Grand Prix", W + "1989_Australian_Grand_Prix"
            ),
        ],
        circuits=[
            CircuitRow(22, "Suzuka Circuit", W + "Suzuka_Circuit"),
            CircuitRow(80, "Las Vegas Strip", W + "Las_Vegas_Grand_Prix#Circuit"),
        ],
        drivers=[
            DriverRow(102, "Ayrton Senna", W + "Ayrton_Senna", wins=41),
            DriverRow(
                117, "Alain Prost", "http://en.wikipedia.org/wiki/Alain_Prost", wins=51
            ),
            DriverRow(900, "Back Marker", W + "Back_Marker", starts=3),
            DriverRow(417, "Thomas Monarch", "http://en.wikipedia.org/wiki/Talk:X#Y"),
        ],
        constructors=[
            ConstructorRow(
                1, "Cooper-Climax", W + "Cooper_Car_Company", frozenset({1959}), 1
            ),
            ConstructorRow(
                2, "Cooper-Maserati", W + "Cooper_Car_Company", frozenset({1966})
            ),
            ConstructorRow(3, "Minnow", W + "Minnow_Racing", frozenset({1990})),
        ],
        driver_refs={"senna": 102, "prost": 117},
        constructor_refs={"cooper": 1, "mclaren": 7},
        circuit_refs={"suzuka": 22},
    )


def _by_title(articles: list[Selected]) -> dict[str, Selected]:
    return {a.title: a for a in articles}


def test_select_articles_applies_the_rules() -> None:
    selection = select_articles(_rows(), [])

    got = _by_title(selection.articles)
    assert got["1989 Formula One season"].depth == Depth.FULL
    assert got["1989 Formula One season"].season == 1989
    race = got["1989 Japanese Grand Prix"]
    assert (race.depth, race.season, race.race_id, race.circuit_id) == (
        Depth.RACE,
        1989,
        480,
        22,
    )
    assert got["Suzuka Circuit"].depth == Depth.CIRCUIT
    vegas = got["Las Vegas Grand Prix"]
    assert (vegas.circuit_id, vegas.anchor) == (80, "Circuit")
    assert got["Ayrton Senna"].depth == Depth.FULL
    assert got["Alain Prost"].driver_ids == (117,)
    assert got["Back Marker"].depth == Depth.LEAD
    # Two constructor rows share one article: one entry, both ids, rule applied once.
    cooper = got["Cooper Car Company"]
    assert (cooper.depth, cooper.constructor_ids) == (Depth.FULL, (1, 2))
    assert got["Minnow Racing"].depth == Depth.LEAD
    assert [a.title for a in selection.articles] == sorted(got)

    skipped = {s.source: s.reason for s in selection.skipped}
    assert skipped == {
        "season 1990": "no Wikipedia URL",
        "driver 417 (Thomas Monarch)": "not an article (a Talk page)",
    }


def test_topics_add_articles_and_upgrade_selected_ones() -> None:
    topics = [
        Topic(
            title="1989 Japanese Grand Prix",
            group=Group.ICONIC_RACE,
            drivers=("senna", "prost"),
        ),
        Topic(
            title="Prost–Senna rivalry",
            group=Group.RIVALRY,
            drivers=("prost", "senna"),
            constructors=("mclaren",),
            season=1989,
            circuit="suzuka",
        ),
        Topic(title="Back Marker", group=Group.SAFETY),
    ]

    got = _by_title(select_articles(_rows(), topics).articles)

    race = got["1989 Japanese Grand Prix"]
    assert race.depth == Depth.FULL
    assert race.kinds == (Kind.RACE, Kind.TOPIC)
    assert (race.race_id, race.topic, race.driver_ids) == (
        480,
        "iconic_race",
        (102, 117),
    )
    rivalry = got["Prost–Senna rivalry"]
    assert rivalry.kinds == (Kind.TOPIC,)
    assert (rivalry.season, rivalry.circuit_id) == (1989, 22)
    assert (rivalry.driver_ids, rivalry.constructor_ids) == ((102, 117), (7,))
    assert got["Back Marker"].depth == Depth.FULL  # lead-only driver upgraded


def test_unknown_topic_refs_are_all_reported() -> None:
    topics = [
        Topic(title="A", group=Group.RIVALRY, drivers=("senna", "nobody")),
        Topic(title="B", group=Group.CAR, constructors=("ghost",), circuit="mars"),
    ]
    with pytest.raises(SelectionError) as exc:
        select_articles(_rows(), topics)
    message = str(exc.value)
    assert "'A': unknown driver ref 'nobody'" in message
    assert "'B': unknown constructor ref 'ghost'" in message
    assert "'B': unknown circuit ref 'mars'" in message


def test_summarise() -> None:
    articles = select_articles(_rows(), []).articles
    counts = summarise(articles)
    assert counts["depth"] == {"full": 4, "race": 2, "circuit": 2, "lead": 2}
    assert counts["kind"]["constructor"] == 2
    assert counts["kind"]["topic"] == 0


# --- resolving against Wikipedia ---


@pytest.fixture
def wiki() -> FakeWiki:
    w = FakeWiki()
    w.add("1989 Formula One World Championship", 10, 1000)
    w.add("Ayrton Senna", 11, 1100)
    w.add("Prost–Senna rivalry", 12, 1200)
    w.add("Senna (disambiguation)", 13, 1300, disambiguation=True)
    w.redirects["1989 Formula One season"] = "1989 Formula One World Championship"
    w.redirects["Senna"] = "Ayrton Senna"
    w.redirects["Senna names"] = "Senna (disambiguation)"
    return w


@pytest.fixture
def client(wiki: FakeWiki) -> WikiClient:
    return WikiClient("ua", 0.1, opener=wiki, clock=lambda: 0.0, sleep=lambda s: None)


def _sel(title: str, *kinds: Kind, depth: Depth = Depth.LEAD, **kw) -> Selected:
    return Selected(title=title, kinds=kinds, depth=depth, **kw)


def test_resolve_follows_redirects_and_merges_duplicates(
    client: WikiClient, wiki: FakeWiki
) -> None:
    articles = [
        _sel("1989 Formula One season", Kind.SEASON, depth=Depth.FULL, season=1989),
        _sel("Ayrton Senna", Kind.DRIVER, depth=Depth.FULL, driver_ids=(102,)),
        _sel("Senna", Kind.CONSTRUCTOR, constructor_ids=(5,)),
        _sel("Gone", Kind.DRIVER, driver_ids=(9,)),
        _sel("Senna names", Kind.DRIVER, driver_ids=(8,)),
    ]

    result = resolve_selection(articles, client)

    got = _by_title(result.articles)
    assert set(got) == {"1989 Formula One World Championship", "Ayrton Senna"}
    season = got["1989 Formula One World Championship"]
    assert (season.pageid, season.season) == (10, 1989)
    senna = got["Ayrton Senna"]
    assert (senna.pageid, senna.driver_ids, senna.constructor_ids) == (11, (102,), (5,))
    assert senna.kinds == (Kind.DRIVER, Kind.CONSTRUCTOR)
    assert result.merged == [("Senna", "Ayrton Senna")]
    assert [a.title for a in result.missing] == ["Gone"]
    assert [a.title for a in result.disambiguation] == ["Senna names"]
    # One batched query for five titles.
    assert len(wiki.calls) == 1
    assert wiki.calls[0]["ppprop"] == "disambiguation"


@pytest.mark.parametrize(
    ("articles", "problem"),
    [
        ([_sel("Gone", Kind.TOPIC, topic="safety")], "'Gone' is not on Wikipedia"),
        (
            [_sel("Senna names", Kind.TOPIC, topic="people")],
            "'Senna names' is a disambiguation page",
        ),
        (
            [
                _sel("Ayrton Senna", Kind.TOPIC, topic="people"),
                _sel("Senna", Kind.TOPIC, topic="people"),
            ],
            "'Ayrton Senna' and 'Senna' are the same article",
        ),
    ],
)
def test_bad_topics_fail_resolution(
    client: WikiClient, articles: list[Selected], problem: str
) -> None:
    with pytest.raises(SelectionError, match="topics.yaml") as exc:
        resolve_selection(articles, client)
    assert problem in str(exc.value)


def test_topic_on_a_redirected_entity_upgrades_it(client: WikiClient) -> None:
    articles = [
        _sel("Senna", Kind.DRIVER, driver_ids=(102,)),
        _sel("Ayrton Senna", Kind.TOPIC, depth=Depth.FULL, topic="people"),
    ]

    (senna,) = resolve_selection(articles, client).articles

    assert (senna.depth, senna.topic, senna.driver_ids) == (
        Depth.FULL,
        "people",
        (102,),
    )


# --- title overrides ---


def test_overrides_replace_stale_urls_and_are_curated() -> None:
    rows = _rows()
    rows.driver_refs["monarch"] = 417
    overrides = [
        TitleOverride(Kind.DRIVER, "senna", "Ayrton Senna (racing driver)"),
        # Overrides also rescue entities whose URL can't be used at all.
        TitleOverride(Kind.DRIVER, "monarch", "Thomas Monarch"),
        TitleOverride(Kind.CONSTRUCTOR, "cooper", "Cooper (constructor)"),
        TitleOverride(Kind.CIRCUIT, "suzuka", "Suzuka International Racing Course"),
    ]

    selection = select_articles(rows, [], overrides)

    got = _by_title(selection.articles)
    assert "Ayrton Senna" not in got
    assert got["Ayrton Senna (racing driver)"].driver_ids == (102,)
    assert got["Ayrton Senna (racing driver)"].depth == Depth.FULL
    assert got["Thomas Monarch"].driver_ids == (417,)
    assert "driver 417 (Thomas Monarch)" not in {s.source for s in selection.skipped}
    # Only the overridden Cooper row moves; the other row keeps the URL's article.
    assert got["Cooper (constructor)"].constructor_ids == (1,)
    assert got["Cooper Car Company"].constructor_ids == (2,)
    assert got["Suzuka International Racing Course"].circuit_id == 22
    assert got["Suzuka International Racing Course"].anchor is None
    assert selection.curated == {
        "Ayrton Senna (racing driver)",
        "Thomas Monarch",
        "Cooper (constructor)",
        "Suzuka International Racing Course",
    }


def test_topic_titles_are_curated() -> None:
    topics = [Topic(title="Prost–Senna rivalry", group=Group.RIVALRY)]
    assert select_articles(_rows(), topics).curated == {"Prost–Senna rivalry"}


def test_bad_overrides_are_reported() -> None:
    overrides = [
        TitleOverride(Kind.DRIVER, "nobody", "X"),
        TitleOverride(Kind.CIRCUIT, "senna", "Y"),  # a driver ref, not a circuit
        TitleOverride(Kind.DRIVER, "prost", "Alain Prost"),  # same as the URL
    ]
    with pytest.raises(SelectionError) as exc:
        select_articles(_rows(), [], overrides)
    message = str(exc.value)
    assert "title_overrides.csv: unknown driver ref 'nobody'" in message
    assert "title_overrides.csv: unknown circuit ref 'senna'" in message
    assert "driver 117 (Alain Prost) already links to 'Alain Prost'" in message


def test_curated_titles_must_resolve(client: WikiClient) -> None:
    articles = [
        _sel("Gone", Kind.DRIVER, driver_ids=(9,)),
        _sel("Senna names", Kind.DRIVER, driver_ids=(8,)),
        _sel("Also gone", Kind.DRIVER, driver_ids=(7,)),
    ]

    with pytest.raises(SelectionError) as exc:
        resolve_selection(articles, client, curated={"Gone", "Senna names"})

    message = str(exc.value)
    assert "'Gone' is not on Wikipedia" in message
    assert "'Senna names' is a disambiguation page" in message
    assert "Also gone" not in message  # from the data: dropped, not an error
