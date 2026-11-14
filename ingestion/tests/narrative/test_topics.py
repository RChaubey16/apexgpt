from pathlib import Path

import pytest

from narrative.errors import SelectionError
from narrative.topics import TOPICS_FILE, Group, parse_topics, read_topics


def test_parse_topics() -> None:
    topics = parse_topics(
        {
            "rivalry": [
                {
                    "title": "Prost–Senna_rivalry",
                    "drivers": ["prost", "senna"],
                    "constructors": ["mclaren"],
                    "season": 1989,
                    "circuit": "suzuka",
                }
            ],
            "concept": [{"title": "safety car"}],
        }
    )

    assert [(t.title, t.group) for t in topics] == [
        ("Prost–Senna rivalry", Group.RIVALRY),
        ("Safety car", Group.CONCEPT),
    ]
    assert topics[0].drivers == ("prost", "senna")
    assert topics[0].season == 1989
    assert topics[1].drivers == ()


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        (None, "expected a mapping"),
        ([], "expected a mapping"),
        ({}, "expected a mapping"),
        ({"gossip": [{"title": "A"}]}, "unknown group 'gossip'"),
        ({"rivalry": []}, "expected a non-empty list"),
        ({"rivalry": {"title": "A"}}, "expected a non-empty list"),
        ({"rivalry": ["A"]}, "rivalry[1]"),
        ({"rivalry": [{"drivers": ["senna"]}]}, "rivalry[1] title"),
        ({"rivalry": [{"title": ""}]}, "title is empty"),
        ({"rivalry": [{"title": "A|B"}]}, "forbids"),
        ({"rivalry": [{"title": "A", "colour": "red"}]}, "colour"),
        ({"rivalry": [{"title": "A", "season": 1949}]}, "season"),
        ({"rivalry": [{"title": "A", "season": 2026}]}, "season"),
        ({"rivalry": [{"title": "A", "drivers": ["Senna"]}]}, "invalid ref 'Senna'"),
        ({"rivalry": [{"title": "A", "drivers": ["a b"]}]}, "invalid ref"),
        ({"rivalry": [{"title": "A", "drivers": ["x", "x"]}]}, "listed twice"),
        ({"rivalry": [{"title": "A", "drivers": "senna"}]}, "drivers"),
        ({"rivalry": [{"title": "A", "circuit": "Monza!"}]}, "circuit"),
        (
            {"rivalry": [{"title": "A"}], "safety": [{"title": "a"}]},
            "safety[1]: 'A' is already listed (rivalry[1])",
        ),
    ],
)
def test_invalid_topics(data: object, problem: str) -> None:
    with pytest.raises(SelectionError) as exc:
        parse_topics(data)
    assert problem in str(exc.value)


def test_all_problems_are_reported_together() -> None:
    with pytest.raises(SelectionError) as exc:
        parse_topics({"gossip": [{"title": "A"}], "rivalry": [{"title": "B|"}]})
    assert "gossip" in str(exc.value)
    assert "rivalry[1]" in str(exc.value)


def test_read_topics_errors(tmp_path: Path) -> None:
    with pytest.raises(SelectionError, match="cannot read"):
        read_topics(tmp_path / "missing.yaml")

    bad = tmp_path / "bad.yaml"
    bad.write_text("rivalry:\n  - title: [unclosed\n")
    with pytest.raises(SelectionError, match=r"not valid YAML \(line \d+\)"):
        read_topics(bad)

    # safe_load: YAML tags that construct Python objects are refused.
    unsafe = tmp_path / "unsafe.yaml"
    unsafe.write_text("rivalry: !!python/object/apply:os.system [echo hi]\n")
    with pytest.raises(SelectionError, match="not valid YAML"):
        read_topics(unsafe)


def test_oversized_topics_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from narrative import topics as topics_module

    monkeypatch.setattr(topics_module, "MAX_FILE_BYTES", 10)
    path = tmp_path / "t.yaml"
    path.write_text("rivalry:\n  - title: A long enough title\n")
    with pytest.raises(SelectionError, match="unexpectedly large"):
        read_topics(path)


def test_the_real_topics_file_is_valid() -> None:
    topics = read_topics(TOPICS_FILE)

    groups = {t.group for t in topics}
    assert groups == set(Group)  # every group is used
    assert 120 <= len(topics) <= 200
    titles = {t.title for t in topics}
    assert "Prost–Senna rivalry" in titles
    assert "1989 Japanese Grand Prix" in titles
