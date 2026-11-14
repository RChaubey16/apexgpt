"""Cleaner tests on synthetic HTML shaped like MediaWiki's action=parse output."""

import pytest

from narrative.cleaner import (
    CleanError,
    clean_article,
    clean_text,
    is_boilerplate,
    normalise_heading,
)
from narrative.selection import Depth


def h(level: int, text: str) -> str:
    """A heading as action=parse renders it."""
    anchor = text.replace(" ", "_")
    return (
        f'<div class="mw-heading mw-heading{level}">'
        f'<h{level} id="{anchor}">{text}</h{level}></div>'
    )


def page(*parts: str) -> str:
    return (
        '<div class="mw-content-ltr mw-parser-output" lang="en">'
        + "".join(parts)
        + "</div>"
    )


def sections(html: str, depth: Depth = Depth.FULL, anchor: str | None = None):
    return {s.path: s.text for s in clean_article(html, depth, anchor).sections}


RACE = page(
    '<div class="shortdescription nomobile noexcerpt">Formula One motor race</div>',
    "<style>.mw-parser-output .infobox{width:22em}</style>",
    '<table class="infobox vevent"><tr><td>Race details</td></tr></table>',
    "<p>The <b>1990 Japanese Grand Prix</b> was held at Suzuka"
    '<span class="geo-inline-hidden noexcerpt"><span class="geo-default">'
    "34°50′N 136°32′E﻿ / ﻿34.84°N</span></span>."
    '<sup id="cite_ref-1" class="reference"><a href="#cite_note-1">[1]</a></sup>'
    " It decided the title.</p>",
    '<p class="mw-empty-elt"></p>',
    h(2, "Background"),
    '<div role="note" class="hatnote navigation-not-searchable">Main article: X</div>',
    '<p>Senna led Prost by nine points.<sup class="noprint Inline-Template Template-Fact">'
    "[<i>citation needed</i>]</sup></p>",
    '<figure class="mw-default-size"><img src="x.jpg"/><figcaption>Senna in 1990</figcaption></figure>',
    h(2, "Practice"),
    "<p>Practice was dry.</p>",
    h(2, "Qualifying"),
    h(3, "Qualifying report"),
    "<p>Senna took pole.</p>",
    h(3, "Qualifying classification"),
    '<table class="wikitable"><tr><td>1</td><td>Senna</td></tr></table>',
    "<p>Source:</p>",
    h(2, "Race"),
    h(3, "Race report"),
    "<p>Senna and Prost collided at the first corner.</p>",
    h(3, "Reaction"),
    "<p>Prost called it disgusting.</p>",
    h(3, "Race classification"),
    '<table class="wikitable"><tr><td>1</td><td>Piquet</td></tr></table>',
    "<dl><dt>Notes</dt><dd>^1 – Moreno was promoted.</dd></dl>",
    h(2, "Diffuser ban and controversy"),
    "<p>A dispute followed.</p>",
    h(2, "Championship standings after the race"),
    "<p>Note: Only the top five positions are included.</p>",
    h(2, "References"),
    '<div class="mw-references-wrap"><ol class="references"><li>Henry, Alan.</li></ol></div>',
    h(2, "External links"),
    "<ul><li>Official site</li></ul>",
    '<div class="navbox" role="navigation"><table><tr><td>1990 season</td></tr></table></div>',
    "<!-- NewPP limit report -->",
)


def test_full_depth_strips_furniture_and_boilerplate() -> None:
    got = sections(RACE)

    assert (
        got[()]
        == "The 1990 Japanese Grand Prix was held at Suzuka. It decided the title."
    )
    assert got[("Background",)] == "Senna led Prost by nine points."
    assert got[("Qualifying", "Qualifying report")] == "Senna took pole."
    assert (
        got[("Race", "Race report")] == "Senna and Prost collided at the first corner."
    )
    assert got[("Race", "Reaction")] == "Prost called it disgusting."
    # Classification, standings, references, links: gone, with their table notes.
    assert set(got) == {
        (),
        ("Background",),
        ("Practice",),
        ("Qualifying", "Qualifying report"),
        ("Race", "Race report"),
        ("Race", "Reaction"),
        ("Diffuser ban and controversy",),
    }
    text = "\n".join(got.values())
    for junk in (
        "infobox",
        "34°",
        "[1]",
        "citation needed",
        "Main article",
        "Senna in 1990",
        "Piquet",
        "Source",
        "Moreno",
        "Henry",
        "Official site",
        "1990 season",
        "NewPP",
        "Formula One motor race",
        "﻿",
    ):
        assert junk not in text, junk


def test_race_depth_keeps_the_race_but_not_sessions() -> None:
    got = sections(RACE, Depth.RACE)

    assert set(got) == {
        (),
        ("Background",),
        ("Race", "Race report"),
        ("Race", "Reaction"),
        ("Diffuser ban and controversy",),  # unusual narrative headings are kept
    }


@pytest.mark.parametrize(
    "heading",
    [
        "Practice",
        "Free practice",
        "Qualifying",
        "Practice and qualifying",
        "Warm-up",
        "Sprint",
        "Sprint shootout",
        "Time trials",
        "Friday drivers",
        "Shared drives",
        "Broadcasting",
        "Championship permutations",
        "Entries",
        "World Drivers' Championship",
    ],
)
def test_race_session_sections_are_skipped(heading: str) -> None:
    html = page("<p>Lead.</p>", h(2, heading), "<p>Session text.</p>")
    assert sections(html, Depth.RACE) == {(): "Lead."}


@pytest.mark.parametrize(
    "heading",
    ["Report", "Race report", "Race summary", "Pre-race", "Post-race", "Aftermath"],
)
def test_race_narrative_sections_are_kept(heading: str) -> None:
    html = page("<p>Lead.</p>", h(2, heading), h(3, "Background"), "<p>Story.</p>")
    assert sections(html, Depth.RACE)[(heading, "Background")] == "Story."


CIRCUIT = page(
    "<p>Suzuka is a circuit.</p>",
    h(2, "History"),
    "<p>Built by Honda.</p>",
    h(3, "Layout history"),
    "<p>Figure-eight since 1962.</p>",
    h(2, "Layout"),
    "<p>Eighteen corners.</p>",
    h(2, "Fatal accidents"),
    "<p>Two drivers died.</p>",
    h(2, "Events"),
    "<ul><li>Japanese Grand Prix</li></ul>",
    h(2, "Concerts"),
    "<p>A concert.</p>",
    h(2, "Lap records"),
    "<p>The lap record is 1:30.</p>",
)


def test_circuit_depth_keeps_history_and_track_sections() -> None:
    got = sections(CIRCUIT, Depth.CIRCUIT)

    assert set(got) == {
        (),
        ("History",),
        ("History", "Layout history"),
        ("Layout",),
        ("Fatal accidents",),
    }


def test_circuit_anchor_keeps_the_named_section() -> None:
    got = sections(CIRCUIT, Depth.CIRCUIT, anchor="Concerts")
    assert got[("Concerts",)] == "A concert."
    assert ("Events",) not in got


def test_lead_depth_keeps_only_the_intro() -> None:
    assert sections(CIRCUIT, Depth.LEAD) == {(): "Suzuka is a circuit."}


DRIVER = page(
    '<table class="infobox biography vcard"><tr><td>Born 1969</td></tr></table>',
    "<p>Michael Schumacher is a German former racing driver.</p>",
    h(2, "Formula One career"),
    h(3, "Ferrari (1996–2006)"),
    h(4, "2000–2004: Five titles"),
    "<p>He won five titles.</p>",
    h(2, "Racing record"),
    h(3, "Career summary"),
    "<p>Summary note.</p>",
    h(3, "Complete Formula One World Championship results"),
    "<p>(key)</p>",
    h(2, "Helmet"),
    "<p>A red helmet.</p>",
    h(2, "Books"),
    "<ul><li>Hilton, Christopher (2006). Michael Schumacher. ISBN 1-84425-284-6.</li></ul>",
    h(2, "General and cited references"),
    "<ul><li>A book.</li></ul>",
)


def test_heading_paths_and_boilerplate_subsections() -> None:
    got = sections(DRIVER)

    assert got == {
        (): "Michael Schumacher is a German former racing driver.",
        (
            "Formula One career",
            "Ferrari (1996–2006)",
            "2000–2004: Five titles",
        ): "He won five titles.",
    }


def test_skipped_heading_levels_keep_a_clean_path() -> None:
    html = page(
        h(2, "Career"), h(4, "Deep"), "<p>Text.</p>", h(3, "Next"), "<p>More.</p>"
    )
    assert sections(html) == {("Career", "Deep"): "Text.", ("Career", "Next"): "More."}


def test_lists_definition_lists_quotes_and_wrapper_divs() -> None:
    html = page(
        "<p>Lead.</p>",
        h(2, "Changes"),
        "<ul><li>Lotus left.</li><li>Brabham <b>returned</b>.</li><li> </li></ul>",
        "<ol><li>First.</li></ol>",
        "<dl><dd>An indented remark.</dd></dl>",
        '<blockquote class="templatequote"><p>"It had to be."</p></blockquote>',
        "<div><p>Inside a wrapper.</p>"
        + h(3, "Wrapped heading")
        + "<p>Under it.</p></div>",
    )

    got = sections(html)

    assert got[("Changes",)] == (
        "- Lotus left.\n- Brabham returned.\n\n- First.\n\n"
        'An indented remark.\n\n"It had to be."\n\nInside a wrapper.'
    )
    assert got[("Changes", "Wrapped heading")] == "Under it."


def test_text_around_removed_inline_elements_is_kept() -> None:
    html = page(
        '<p>He won.<sup class="reference">[1]</sup><sup class="reference">[2]</sup> '
        'Then he<span class="flagicon"><img src="f.png"/></span> retired.</p>'
    )
    assert sections(html) == {(): "He won. Then he retired."}


def test_sections_without_text_are_dropped() -> None:
    html = page(
        "<p>Lead.</p>",
        h(2, "Results"),
        '<table class="wikitable"><tr><td>1</td></tr></table>',
    )
    assert sections(html) == {(): "Lead."}


@pytest.mark.parametrize(
    "html",
    [
        "<p>Plain.</p>",
        "<p>Plain.</p><p>Second.</p>",
        '<div class="mw-parser-output"><p>Plain.</p></div><p>Outside.</p>',
    ],
)
def test_article_shapes(html: str) -> None:
    assert sections(html)[()].startswith("Plain.")


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("  Senna \n\t won  ", "Senna won"),
        ("Prost\xa0won", "Prost won"),
        ("He won [1] , then [a] retired [citation needed] .", "He won, then retired."),
        ("( 1990 )", "(1990)"),
        ("zero​width﻿­", "zerowidth"),
        ("Saleen site Archived 2014-07-14 at the Wayback Machine.", "Saleen site."),
        ("Räikkönen", "Räikkönen"),  # combining marks -> NFC
        ("[note 3]Kept", "Kept"),
    ],
)
def test_clean_text(raw: str, clean: str) -> None:
    assert clean_text(raw) == clean


@pytest.mark.parametrize(
    ("heading", "boilerplate"),
    [
        ("References", True),
        ("  See   also ", True),
        ("Notes and references", True),
        ("General and cited references", True),
        ("Complete Formula One World Championship results", True),
        ("Indianapolis 500 results", True),
        ("Karting record", True),
        ("Lap records", True),
        ("Final Championship standings", True),
        ("List of works", True),
        ("Helmet", True),
        ("Formula One career", False),
        ("Race", False),
        ("Results of the inquiry into the crash", False),
        ("Legacy", False),
    ],
)
def test_is_boilerplate(heading: str, boilerplate: bool) -> None:
    assert is_boilerplate(heading) is boilerplate


def test_normalise_heading() -> None:
    assert normalise_heading("  Race   Report ") == "race report"


@pytest.mark.parametrize("html", ["", "   "])
def test_empty_html_is_an_error(html: str) -> None:
    with pytest.raises(CleanError, match="empty"):
        clean_article(html, Depth.FULL)


def test_oversized_html_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("narrative.cleaner.MAX_HTML_BYTES", 10)
    with pytest.raises(CleanError, match="unexpectedly large"):
        clean_article("<p>more than ten bytes</p>", Depth.FULL)


def test_html_without_text_gives_no_sections() -> None:
    assert clean_article("<!-- only a comment -->", Depth.FULL).sections == []
    assert clean_article("<table><tr><td>1</td></tr></table>", Depth.FULL).words == 0


def test_tables_nested_in_text_blocks_are_removed() -> None:
    # The walker never reads top-level tables; these sit inside blocks it does read.
    cell = '<table class="wikitable"><tr><td>P1 Senna 1:38.041</td></tr></table>'
    html = page(
        f"<ul><li>Pole position{cell}</li></ul>",
        f"<dl><dd>Notes{cell}</dd></dl>",
        f"<blockquote>Quote{cell}</blockquote>",
        '<p>Lead<span class="infobox">Born 1960</span> text.</p>',
    )

    text = "\n".join(sections(html).values())

    assert "Senna" not in text and "Born" not in text
    assert "- Pole position" in text and "Lead text." in text
