import pytest

from narrative.chunker import (
    MAX_TOKENS,
    MODEL_MAX_TOKENS,
    OVERLAP_TOKENS,
    TARGET_TOKENS,
    Chunk,
    ChunkError,
    chunk_sections,
    estimate_tokens,
    split_sentences,
)

TITLE = "1990 Japanese Grand Prix"


def sentences(count: int, start: int = 0, word: str = "lap") -> list[str]:
    # 10 words, 14 estimated tokens each.
    return [
        f"Senna passed Prost on {word} {i} at the Suzuka chicane."
        for i in range(start, start + count)
    ]


def paragraph(count: int, start: int = 0, word: str = "lap") -> str:
    return " ".join(sentences(count, start, word))


def all_text(chunks: list[Chunk]) -> str:
    return "\n\n".join(c.text for c in chunks)


def test_estimate_tokens_is_words_times_ratio_rounded_up() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("one") == 2
    assert estimate_tokens("Senna passed  Prost\non lap 1.") == 9  # 6 words x 1.4


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Senna won. Prost retired.", ["Senna won.", "Prost retired."]),
        ("Did he crash? Yes! Then rain.", ["Did he crash?", "Yes!", "Then rain."]),
        ('He said "no." Then left.', ['He said "no."', "Then left."]),
        ("Senna (on pole.) Won.", ["Senna (on pole.)", "Won."]),
        (
            "J. M. Fangio won. Moss was second.",
            ["J. M. Fangio won.", "Moss was second."],
        ),
        (
            "He crashed at St. Devote. Then rain.",
            ["He crashed at St. Devote.", "Then rain."],
        ),
        ("The No. 1 driver vs. Prost.", ["The No. 1 driver vs. Prost."]),
        (
            "A 1.5 litre engine. In 1961 it won.",
            ["A 1.5 litre engine.", "In 1961 it won."],
        ),
        ("lower case. after a stop", ["lower case. after a stop"]),
        ("", []),
    ],
)
def test_split_sentences(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


def test_short_article_is_one_chunk_per_top_level_section() -> None:
    chunks = chunk_sections(
        TITLE,
        [
            ((), "The 1990 Japanese Grand Prix was held at Suzuka."),
            (("Background",), "Senna led Prost by nine points."),
            (("Race",), "Senna and Prost collided at the first corner."),
        ],
    )

    # tokens = heading ("1990 Japanese Grand Prix > Race") + text, estimated
    assert chunks == [
        Chunk((), "The 1990 Japanese Grand Prix was held at Suzuka.", 6 + 13),
        Chunk(("Background",), "Senna led Prost by nine points.", 9 + 9),
        Chunk(("Race",), "Senna and Prost collided at the first corner.", 9 + 12),
    ]


def test_small_subsections_are_packed_under_their_heading() -> None:
    chunks = chunk_sections(
        "Michael Schumacher",
        [
            ((), "Schumacher is a German former racing driver."),
            (("Formula One career", "Jordan (1991)"), "He debuted at Spa."),
            (("Formula One career", "Benetton (1991–1995)"), "He won two titles."),
            (
                ("Formula One career", "Benetton (1991–1995)", "1994"),
                "His first title.",
            ),
            (("Personal life",), "He married Corinna in 1995."),
        ],
    )

    assert [c.path for c in chunks] == [(), ("Formula One career",), ("Personal life",)]
    assert chunks[1].text == (
        "Jordan (1991)\n\nHe debuted at Spa.\n\n"
        "Benetton (1991–1995)\n\nHe won two titles.\n\n"
        "Benetton (1991–1995) > 1994\n\nHis first title."
    )


def test_packed_chunk_is_labelled_with_the_shared_heading_path() -> None:
    chunks = chunk_sections(
        TITLE,
        [
            (("Race", "Start"), "Senna and Prost collided."),
            (("Race", "Start", "Aftermath"), "Both retired."),
        ],
    )

    assert [(c.path, c.text) for c in chunks] == [
        (("Race", "Start"), "Senna and Prost collided.\n\nAftermath\n\nBoth retired.")
    ]


def test_the_lead_is_never_packed_with_sections() -> None:
    chunks = chunk_sections(
        TITLE, [((), "Lead."), (("A",), "One."), (("A", "B"), "Two.")]
    )

    assert [c.path for c in chunks] == [(), ("A",)]


def test_a_section_that_would_overflow_the_chunk_starts_a_new_one() -> None:
    chunks = chunk_sections(
        TITLE,
        [
            (("Race", "Start"), paragraph(20)),  # 280 tokens
            (("Race", "Middle"), paragraph(20, 20)),
            (("Race", "End"), paragraph(5, 40)),  # 70: fits with the one before
        ],
    )

    assert [c.path for c in chunks] == [("Race", "Start"), ("Race",)]
    assert chunks[1].text.startswith("Middle\n\nSenna passed Prost on lap 20 ")
    assert "\n\nEnd\n\nSenna passed Prost on lap 40 " in chunks[1].text


def test_a_long_section_is_split_into_balanced_parts_that_overlap() -> None:
    text = "\n\n".join(paragraph(4, i * 4) for i in range(18))  # 1,008 tokens
    chunks = chunk_sections(TITLE, [(("Race",), text)])

    assert len(chunks) == 3
    assert all(c.path == ("Race",) for c in chunks)
    sizes = [c.tokens for c in chunks]
    assert max(sizes) - min(sizes) <= 80
    for before, after in zip(chunks, chunks[1:], strict=False):
        # The next part starts with the last sentences (<= ~50 tokens) of the
        # previous one, and then a new paragraph.
        last_sentences = split_sentences(before.text.split("\n\n")[-1])
        carried = after.text.split("\n\n")[0]
        assert carried == " ".join(last_sentences[-3:])
        assert estimate_tokens(carried) <= OVERLAP_TOKENS


def test_split_parts_cover_the_whole_section_in_order() -> None:
    original = sentences(150)
    text = "\n\n".join(" ".join(original[i : i + 5]) for i in range(0, 150, 5))
    chunks = chunk_sections(TITLE, [(("Race",), text)])

    seen: list[str] = []
    for chunk in chunks:
        for sentence in split_sentences(chunk.text.replace("\n\n", " ")):
            if not seen or sentence not in seen:
                seen.append(sentence)
    assert seen == original


def test_no_overlap_across_sections() -> None:
    chunks = chunk_sections(
        TITLE,
        [
            (("Race",), paragraph(40, word="lap")),
            (("Aftermath",), paragraph(40, word="day")),
        ],
    )

    race = [c for c in chunks if c.path == ("Race",)]
    aftermath = [c for c in chunks if c.path == ("Aftermath",)]
    assert len(race) == 2 and len(aftermath) == 2
    assert all(" day " not in c.text for c in race)
    assert all(" lap " not in c.text for c in aftermath)
    # Within a section, consecutive parts do overlap.
    assert race[0].text.split()[-10:] == race[1].text.split()[:10]


def test_a_long_paragraph_is_split_at_sentences_and_rejoined_with_spaces() -> None:
    chunks = chunk_sections(
        TITLE, [(("Race",), paragraph(60))]
    )  # one 840-token paragraph

    assert len(chunks) == 2
    for chunk in chunks:
        assert "\n" not in chunk.text
        assert chunk.tokens <= MAX_TOKENS


def test_a_long_list_is_split_at_items() -> None:
    items = "\n".join(f"- Item {i}: " + paragraph(1, i) for i in range(40))  # 40 x 18
    chunks = chunk_sections(TITLE, [(("Notes",), "The changes were:\n" + items)])

    assert len(chunks) == 2
    for chunk in chunks:
        lines = chunk.text.split("\n")
        assert all(line.startswith("- Item ") for line in lines[1:])
    assert chunks[0].text.startswith("The changes were:\n- Item 0: ")


def test_text_without_sentence_breaks_is_split_into_word_windows() -> None:
    words = " ".join(f"word{i}" for i in range(1_000))
    chunks = chunk_sections(TITLE, [(("Race",), words)])

    assert len(chunks) >= 3
    assert all(c.tokens <= MAX_TOKENS for c in chunks)
    joined = " ".join(c.text for c in chunks).split()
    assert [w for i, w in enumerate(joined) if w not in joined[:i]] == words.split()


def test_no_short_leftover_part() -> None:
    # Two ~300-token paragraphs and a short one: the second part takes the
    # short paragraph too, rather than leaving it as a chunk of its own.
    end = paragraph(3, 42)  # 42 tokens
    text = f"{paragraph(21)}\n\n{paragraph(21, 21)}\n\n{end}"
    chunks = chunk_sections(TITLE, [(("Race",), text)])

    assert len(chunks) == 2
    assert chunks[0].text == paragraph(21)
    assert chunks[1].text.endswith(f"{paragraph(21, 21)}\n\n{end}")


def test_every_chunk_fits_the_model_with_its_heading() -> None:
    long_title = "Formula One " * 10
    text = "\n\n".join(paragraph(3, i * 3) for i in range(40))
    chunks = chunk_sections(long_title, [(("History", "Early years"), text)])

    for chunk in chunks:
        heading = " > ".join((long_title, *chunk.path))
        assert estimate_tokens(heading) + estimate_tokens(chunk.text) == chunk.tokens
        assert chunk.tokens <= MAX_TOKENS


def test_custom_sizes() -> None:
    text = "\n\n".join(paragraph(2, i * 2) for i in range(20))  # 560 tokens
    small = chunk_sections(TITLE, [(("Race",), text)], target=150, maximum=200)

    assert len(small) >= 4
    assert all(c.tokens <= 200 for c in small)


def test_empty_sections_are_ignored() -> None:
    assert chunk_sections(TITLE, []) == []
    assert chunk_sections(TITLE, [(("Race",), "  \n ")]) == []


@pytest.mark.parametrize(
    ("target", "maximum"),
    [(0, 100), (200, 100), (TARGET_TOKENS, MODEL_MAX_TOKENS + 1)],
)
def test_rejects_bad_sizes(target: int, maximum: int) -> None:
    with pytest.raises(ValueError, match="need 0 < target"):
        chunk_sections(TITLE, [((), "Text.")], target=target, maximum=maximum)


def test_rejects_headings_that_leave_no_room_for_text() -> None:
    with pytest.raises(ChunkError, match="headings are too long"):
        chunk_sections("word " * 100, [((), "Text.")])


def test_is_deterministic() -> None:
    sections = [((), paragraph(50)), (("Race",), paragraph(80))]
    assert chunk_sections(TITLE, sections) == chunk_sections(TITLE, sections)
