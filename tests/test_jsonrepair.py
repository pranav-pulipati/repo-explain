import pytest

from repo2course.jsonrepair import JSONParseError, parse_json


@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', {"a": 1}),
    ('```json\n{"a": 1}\n```', {"a": 1}),
    ('Sure! Here it is:\n{"a": [1, 2]}\nHope that helps.', {"a": [1, 2]}),
    ('{"a": 1, "b": [1, 2,],}', {"a": 1, "b": [1, 2]}),
    ('{"ok": True, "v": None}', {"ok": True, "v": None}),
    ('{"a": 1 // comment\n}', {"a": 1}),
    ('{“a”: 1}', {"a": 1}),
    ('[{"x": 1}]', [{"x": 1}]),
])
def test_parse_variants(text, expected):
    assert parse_json(text) == expected


def test_braces_inside_strings_are_not_structure():
    assert parse_json('noise {"code": "if (x) { y(); }", "n": 2} trailing') == {"code": "if (x) { y(); }", "n": 2}


def test_literal_words_inside_strings_untouched():
    assert parse_json('{"s": "True or None"}') == {"s": "True or None"}


def test_truncated_output_is_closed():
    assert parse_json('{"items": [{"a": 1}, {"a": 2') == {"items": [{"a": 1}, {"a": 2}]}
    assert parse_json('{"items": ["one", "tw') == {"items": ["one", "tw"]}
    assert parse_json('```json\n{"a": {"b": 1}, "c": ') == {"a": {"b": 1}}


@pytest.mark.parametrize("bad", ["", "   ", "no json here at all"])
def test_unparseable_raises(bad):
    with pytest.raises(JSONParseError):
        parse_json(bad)
