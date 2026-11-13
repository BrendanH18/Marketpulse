"""Row filters 21-30 of #143: regular expressions, globs, text lists, date bounds, array items and object keys.

Every expected row is worked out by hand from the specification's conventions: the report text of a
cell (a string is itself, null is empty, any other value is its canonical JSON), date-like values and
typed equality. Nothing here calls the filter code to build an expectation. Cases the specification
does not settle say so and test what the implementation does; disagreements with the specification
are strict expected failures.
"""

import json
import math
import warnings

import click
import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports, summaries
from marketpulse.cli.base import App
from marketpulse.cli.report_filters import EXPANSION_FILTERS, FILTER_OPTIONS, compile_filters
from marketpulse.models import Account, AccountType, Transaction, TxnType

# A valid value for each new filter, so a test can make exactly one part of a condition wrong.
VALID = {
    "--regex": "x",
    "--not-regex": "x",
    "--iglob": "x",
    "--not-glob": "x",
    "--contains-any": '["x"]',
    "--contains-all": '["x"]',
    "--date-from": "2024-01-01",
    "--date-to": "2024-01-01",
    "--has-item": "1",
    "--has-key": "x",
}
OPTIONS = tuple(VALID)
COMMANDS = ("report", "summarize")


def key_of(option):
    """The compile_filters key of a command-line option, for example contains_any."""
    return option.removeprefix("--").replace("-", "_")


def kept_by(options, values):
    """Positions of the values whose row passes every condition; conditions name the field `value`."""
    predicate = compile_filters(("value", "other"), options)
    return [position for position, value in enumerate(values) if predicate({"value": value, "other": None})]


def kept(option, argument, values):
    return kept_by({option: (argument,)}, values)


def rejected(option, argument):
    with pytest.raises(click.UsageError) as error:
        compile_filters(("value", "other"), {option: (argument,)})
    return error.value.message


def report(*arguments):
    return CliRunner().invoke(main, ["report", "config", *arguments])


def summarize(*arguments):
    return CliRunner().invoke(main, ["summarize", "config", *arguments])


def output(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def serve(monkeypatch, pairs):
    """Serve (key, value) pairs as the rows of the `config` source, whose fields are key and value."""
    rows = [{"key": key, "value": value} for key, value in pairs]
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    return rows


def kept_keys(command, *arguments):
    """The keys of the rows a command keeps: report lists the rows, summarize collects their keys."""
    if command == "report":
        return [row["key"] for row in output(report(*arguments))]
    [summary] = output(summarize(*arguments, "--metric", "keys=values:key"))
    return summary["keys"]


@pytest.fixture
def unloaded(monkeypatch):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("an invalid query loaded the source"))
    monkeypatch.setattr(App, "tracker", property(lambda self: pytest.fail("an invalid query opened the tracker")))


def test_ten_new_repeatable_filters_on_both_commands():
    assert set(EXPANSION_FILTERS) == {key_of(option) for option in OPTIONS}
    assert len(EXPANSION_FILTERS) == 10
    assert not set(EXPANSION_FILTERS) & set(FILTER_OPTIONS)
    for command in (reports.report, summaries.summarize):
        parameters = {name: parameter for parameter in command.params for name in parameter.opts}
        assert all(parameters[option].multiple for option in OPTIONS), command.name


# ---------------------------------------------------------------------------------------------
# Report text. Each comment gives the text a filter reads.

CELLS = [
    "Alpha",  # 0: Alpha
    "alpha beta",  # 1: alpha beta
    "ÉCOLE café",  # 2: ÉCOLE café
    "Straße",  # 3: Straße
    "",  # 4: empty
    None,  # 5: empty
    10,  # 6: 10
    "10",  # 7: 10
    1.0,  # 8: 1.0
    -2.5,  # 9: -2.5
    True,  # 10: true
    False,  # 11: false
    [1, 2],  # 12: [1, 2]
    {"b": "x=y", "a": 1},  # 13: {"a": 1, "b": "x=y"}, keys sorted
    ["café"],  # 14: ["café"], not escaped to ASCII
    "line one\nline two",  # 15: two lines
]
EVERY = list(range(len(CELLS)))


def others(positions):
    return [position for position in EVERY if position not in positions]


# Pattern, then the positions of the texts holding a match.
REGEX = [
    ("lph", [0, 1]),  # searched anywhere, not anchored
    ("alpha", [1]),  # case-sensitive by default
    ("(?i)ALPHA", [0, 1]),
    ("^(?i:al)pha$", [0]),  # a scoped inline flag
    ("^a", [1]),
    ("a$", [0, 1]),
    ("^$", [4, 5]),  # null reads as empty text
    ("", EVERY),  # the empty pattern matches every text
    ("x*", EVERY),  # as does any pattern that can match nothing
    ("^10$", [6, 7]),
    (r"^1\.0$", [8]),
    (r"^-?\d+(\.\d+)?$", [6, 7, 8, 9]),
    ("^(true|false)$", [10, 11]),
    ("1, 2", [12]),
    (r'^\{"a": 1, "b"', [13]),
    ("x=y", [13]),  # only the first = separates FIELD from PATTERN
    ("café", [2, 14]),
    ("(?i)école", [2]),
    ("école", []),
    (r"^\w+$", [0, 3, 6, 7, 10, 11]),  # \w reads Unicode letters, so ß is one
    ("^line two$", []),
    ("(?m)^line two$", [15]),
    ("one.line", []),
    ("(?s)one.line", [15]),
]


@pytest.mark.parametrize(("pattern", "expected"), REGEX, ids=[case[0] or "empty" for case in REGEX])
def test_regex_keeps_texts_holding_a_match_and_not_regex_excludes_them(pattern, expected):
    assert kept("regex", "value=" + pattern, CELLS) == expected
    assert kept("not_regex", "value=" + pattern, CELLS) == others(expected)


# Pattern, then the positions of the texts it matches as a whole, ignoring case.
IGLOB = [
    ("alpha", [0]),
    ("ALPHA*", [0, 1]),
    ("*É*", [2, 14]),
    ("??", [6, 7]),
    ("*", EVERY),
    ("", [4, 5]),  # only empty text, null included
    ("TRUE", [10]),
    ("[TF]*E", [10, 11]),
    ("[a-c]*", [0, 1]),
    ("[!a-z]*", [2, 6, 7, 8, 9, 12, 13, 14]),
    ("[[]1, 2]", [12]),
    ("{*}", [13]),
    ('{"A": 1, "B": *}', [13]),  # object keys are sorted in the text
    ("1.?", [8]),
    ("-?.5", [9]),
    ("LINE*TWO", [15]),  # * also spans a line break
]


@pytest.mark.parametrize(("pattern", "expected"), IGLOB, ids=[case[0] or "empty" for case in IGLOB])
def test_iglob_matches_the_whole_text_ignoring_case(pattern, expected):
    assert kept("iglob", "value=" + pattern, CELLS) == expected


# Pattern, then the positions of the texts it matches as a whole, case-sensitively: the rows excluded.
NOT_GLOB = [
    ("Alpha", [0]),
    ("alpha", []),
    ("*", EVERY),
    ("?*", others([4, 5])),
    ("", [4, 5]),
    ("true", [10]),
    ("TRUE", []),
    ("[A-Z]*", [0, 3]),  # É is not in A-Z
    ("*[0-9]", [6, 7, 8, 9]),
    ("*café*", [2, 14]),
    ("*CAFÉ*", []),
    ("line*two", [15]),
]


@pytest.mark.parametrize(("pattern", "excluded"), NOT_GLOB, ids=[case[0] or "empty" for case in NOT_GLOB])
def test_not_glob_excludes_whole_text_matches_case_sensitively(pattern, excluded):
    assert kept("not_glob", "value=" + pattern, CELLS) == others(excluded)


CONTAINS_ANY = [
    ("[]", []),  # an empty list matches nothing
    ('[""]', EVERY),  # every text contains the empty string, null's included
    ('["ALPHA"]', [0, 1]),
    (' [ "ALPHA" ] ', [0, 1]),  # JSON allows whitespace around values
    ('["CAFÉ", "TRUE"]', [2, 10, 14]),
    ('["1, 2"]', [12]),
    ('["\\"a\\": 1"]', [13]),
    ('["0"]', [6, 7, 8]),
    ('["x=y", "école"]', [2, 13]),
    ('["line one\\nline"]', [15]),  # a JSON escape inside a member
    ('["nope", "zzz"]', []),
]
CONTAINS_ALL = [
    ("[]", EVERY),  # an empty list matches every row
    ('[""]', EVERY),
    ('["al", "BE"]', [1]),
    ('["1", "2"]', [12]),
    ('["TRUE"]', [10]),
    ('["A", "a"]', [0, 1, 2, 3, 11, 13, 14]),
    ('["café", "["]', [14]),
    ('["x=y", "zzz"]', []),
]


@pytest.mark.parametrize(("members", "expected"), CONTAINS_ANY)
def test_contains_any_keeps_texts_holding_one_listed_string(members, expected):
    assert kept("contains_any", "value=" + members, CELLS) == expected


@pytest.mark.parametrize(("members", "expected"), CONTAINS_ALL)
def test_contains_all_keeps_texts_holding_every_listed_string(members, expected):
    assert kept("contains_all", "value=" + members, CELLS) == expected


@pytest.mark.parametrize(
    "pattern",
    [
        "(",
        ")",
        "[",
        "[a-",
        "*",
        "+a",
        "a{2,1}",
        "\\",
        "(?z)",
        "(?L)a",
        "a(?i)b",
        "(?<=a+)b",
        "(?P<x>a)(?P<x>b)",
        r"\N{NO SUCH NAME}",
        r"\p{L}",
        "a{4294967296}",
    ],
)
def test_invalid_regular_expressions_are_rejected_when_compiled(pattern):
    rejected("regex", "value=" + pattern)
    rejected("not_regex", "value=" + pattern)


@pytest.mark.parametrize(
    "members",
    [
        '"x"',
        "{}",
        "1",
        "null",
        "true",
        "[1]",
        '["a", 1]',
        "[null]",
        '[["a"]]',
        '[{"a": "b"}]',
        "[a]",
        '["a"',
        "",
        "'[\"a\"]'",
        '["a"] ["b"]',
        "[NaN]",
        '["a", Infinity]',
    ],
)
def test_contains_lists_must_be_json_arrays_of_strings(members):
    rejected("contains_any", "value=" + members)
    rejected("contains_all", "value=" + members)


# ---------------------------------------------------------------------------------------------
# Unicode case: ß and similar letters.


def test_iglob_keeps_every_text_the_pattern_matches_in_its_exact_case():
    # Each text matches its pattern character for character, so it matches whatever case is ignored.
    cases = [
        ("?", "ß"),
        ("?", "ẞ"),
        ("?", "ﬁ"),
        ("?", "İ"),
        ("Stra?e", "Straße"),
        ("Stra[ß]", "Straß"),
        ("[ß]", "ß"),
        ("?le", "ﬁle"),
    ]
    assert [(pattern, text) for pattern, text in cases if not kept("iglob", "value=" + pattern, [text])] == []


def test_iglob_bracket_class_matches_only_its_own_letters():
    # [ß] is one letter; no case of it is "s", and no case of the ligature ﬁ is "f" or "i".
    assert kept("iglob", "value=[ß]", ["s", "S", "x"]) == []
    assert kept("iglob", "value=[ﬁ]", ["f", "i", "F"]) == []


def test_text_lists_use_full_case_folding_and_iglob_compares_per_character():
    # Unspecified: "ignoring case" does not say whether ß equals SS. The list filters compare
    # str.casefold() text, so ß and ẞ equal ss, and "s" is found inside "ß". --iglob and a --regex
    # "(?i)" pattern ignore case one character at a time, as Python's re module does, so ß equals ẞ
    # but not SS, and ? still matches exactly one character.
    values = ["Straße", "STRASSE", "strasse", "STRAẞE", "Strase", "ß", "s"]
    assert kept("contains_any", 'value=["straße"]', values) == [0, 1, 2, 3]
    assert kept("contains_all", 'value=["STRASSE"]', values) == [0, 1, 2, 3]
    assert kept("contains_any", 'value=["ss"]', values) == [0, 1, 2, 3, 5]
    assert kept("contains_any", 'value=["s"]', values) == [0, 1, 2, 3, 4, 5, 6]
    assert kept("iglob", "value=STRASSE", values) == [1, 2]
    assert kept("iglob", "value=straße", values) == [0, 3]
    assert kept("regex", "value=(?i)^straße$", values) == [0, 3]


def test_unclosed_bracket_in_a_glob_is_literal():
    # Unspecified: a "[" with no closing "]" is not a class; it is matched as itself, not rejected.
    assert kept("iglob", "value=[ABC", ["[abc", "a", "[ABC"]) == [0, 2]
    assert kept("not_glob", "value=[abc", ["[abc", "a", "[ABC"]) == [1, 2]


# ---------------------------------------------------------------------------------------------
# Dates: a string that is YYYY-MM-DD, alone or followed by T or a space and anything.

DATES = [
    "2024-03-04",  # 0: 2024-03-04
    "2024-03-05",  # 1: 2024-03-05
    "2024-03-05T00:00:00Z",  # 2: 2024-03-05
    "2024-03-04T23:59:59",  # 3: 2024-03-04
    "2024-03-05 18:30",  # 4: 2024-03-05
    "2024-03-06 ",  # 5: 2024-03-06, a space and then nothing
    "2024-03-06T",  # 6: 2024-03-06, a T and then nothing
    "2024-03-06T99:99",  # 7: 2024-03-06, anything may follow the T
    "2024-12-31T10:00\nnote",  # 8: 2024-12-31, even a line break
    "2025-01-01",  # 9: 2025-01-01
    "2024-03-04T23:00:00-05:00",  # 10: 2024-03-04, the first ten characters whatever the offset
    "2024-02-30",  # 11 onwards: not date-like
    "2024-02-30T10:00:00",
    "2023-02-29",
    "2024-3-5",
    "20240305",
    "2024-03-05x",
    "2024-03-05t10:00",
    "2024-03-05\t10:00",
    "2024-03-05\n",
    " 2024-03-05",
    "２０２４-０３-０５",  # full-width digits
    "",
    None,
    20240305,
    2024.0305,
    True,
    ["2024-03-05"],
    {"date": "2024-03-05"},
]
DATE_LIKE = list(range(11))

DATE_BOUNDS = [
    ("date_from", "2024-03-05", [1, 2, 4, 5, 6, 7, 8, 9]),  # inclusive
    ("date_to", "2024-03-05", [0, 1, 2, 3, 4, 10]),
    ("date_from", "2024-03-04", DATE_LIKE),
    ("date_to", "2024-03-03", []),
    ("date_from", "2024-03-06", [5, 6, 7, 8, 9]),
    ("date_to", "2024-03-06", [0, 1, 2, 3, 4, 5, 6, 7, 10]),
    ("date_from", "2024-12-31", [8, 9]),
    ("date_to", "2024-03-04", [0, 3, 10]),
    ("date_from", "2025-01-02", []),
    ("date_to", "2025-01-01", DATE_LIKE),
    ("date_from", "0001-01-01", DATE_LIKE),
    ("date_to", "9999-12-31", DATE_LIKE),
]


@pytest.mark.parametrize(("option", "bound", "expected"), DATE_BOUNDS, ids=[f"{c[0]}-{c[1]}" for c in DATE_BOUNDS])
def test_date_bounds_are_inclusive_and_skip_values_that_are_not_date_like(option, bound, expected):
    assert kept(option, "value=" + bound, DATES) == expected


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"date_from": ("value=2024-03-05",), "date_to": ("value=2024-03-05",)}, [1, 2, 4]),
        ({"date_from": ("value=2024-03-05",), "date_to": ("value=2024-12-31",)}, [1, 2, 4, 5, 6, 7, 8]),
        ({"date_from": ("value=2024-03-04", "value=2024-03-06")}, [5, 6, 7, 8, 9]),
        ({"date_to": ("value=2024-12-31", "value=2024-03-04")}, [0, 3, 10]),
    ],
    ids=["one-day", "range", "repeated-from", "repeated-to"],
)
def test_date_bounds_combine_into_ranges(options, expected):
    assert kept_by(options, DATES) == expected


@pytest.mark.parametrize(
    "bound",
    [
        "2024-02-30",
        "2023-02-29",
        "2024-13-01",
        "2024-00-10",
        "2024-01-00",
        "2024-1-1",
        "24-01-01",
        "12024-01-01",
        "+2024-01-01",
        "20240101",
        "2024/01/01",
        "2024-W01-1",
        "",
        " 2024-01-01",
        "2024-01-01 ",
        "2024-01-01\n",
        "2024-01-01T00:00",
        "2024-01-01 00:00",
        "２０２４-０１-０１",
        "today",
    ],
)
def test_date_bounds_must_be_valid_calendar_dates(bound):
    rejected("date_from", "value=" + bound)
    rejected("date_to", "value=" + bound)


def test_year_zero_is_neither_a_bound_nor_a_date():
    # Unspecified: whether 0000-01-01 is "a valid YYYY-MM-DD date". The implementation follows
    # Python's calendar, which starts at 0001-01-01, so it rejects the bound and skips such cells.
    rejected("date_from", "value=0000-01-01")
    rejected("date_to", "value=0000-12-31")
    assert kept("date_to", "value=0001-01-01", ["0000-12-31", "0001-01-01", "0000-01-01T00:00"]) == [1]


# ---------------------------------------------------------------------------------------------
# Array items, by typed equality: false differs from 0, "1" from 1, while 1 equals 1.0.

ARRAYS = [
    [False],  # 0
    [0],  # 1
    [0.0],  # 2
    [1],  # 3
    [1.0],  # 4
    ["1"],  # 5
    [True],  # 6
    [None],  # 7
    [],  # 8
    [[1, 2]],  # 9
    [[2, 1]],  # 10
    [[1.0, 2]],  # 11
    [{"a": 1, "b": [True]}],  # 12
    [1, 2],  # 13
    [[[1]]],  # 14
    [["1"]],  # 15
    ["null"],  # 16
    [""],  # 17
    [[]],  # 18
    [{}],  # 19
    ["a=b"],  # 20
    "[1]",  # 21: text, not an array
    {"1": 1},  # 22: an object
    1,  # 23
    None,  # 24
    True,  # 25
]
HAS_ITEM = [
    ("false", [0]),
    ("0", [1, 2]),
    ("0.0", [1, 2]),
    ("1", [3, 4, 13]),
    ("1.0", [3, 4, 13]),
    ("1e0", [3, 4, 13]),
    (" 1 ", [3, 4, 13]),
    ('"1"', [5]),
    ("true", [6]),
    ("null", [7]),
    ("[1, 2]", [9, 11]),  # the item is the whole array: order matters, 1.0 equals 1
    ("[2,1]", [10]),
    ('{"b": [true], "a": 1}', [12]),  # key order does not matter
    ('{"a": 1.0, "b": [true]}', [12]),
    ('{"a": 1, "b": [1]}', []),  # true inside differs from 1
    ("[[1]]", [14]),
    ('["1"]', [15]),
    ('"null"', [16]),
    ('""', [17]),
    ("[]", [18]),
    ("{}", [19]),
    ('"a=b"', [20]),
    ("2", [13]),
    ('"[1]"', []),
]


@pytest.mark.parametrize(("item", "expected"), HAS_ITEM, ids=[case[0] for case in HAS_ITEM])
def test_has_item_finds_typed_equal_elements_of_arrays_only(item, expected):
    assert kept("has_item", "value=" + item, ARRAYS) == expected


@pytest.mark.parametrize(
    "item",
    [
        "NaN",
        "Infinity",
        "-Infinity",
        "1e999",
        "-1e999",
        "[NaN]",
        '{"a": Infinity}',
        "[1, [1e999]]",
        "nan",
        "",
        "[1",
        "{a: 1}",
        "'x'",
        "x",
        "True",
        "None",
        "1 2",
        "[1,]",
        "01",
        ".5",
        "+1",
    ],
)
def test_has_item_requires_valid_finite_json(item):
    rejected("has_item", "value=" + item)


def test_has_item_refuses_integers_beyond_pythons_digit_limit_cleanly():
    # JSON parsers may limit number range (RFC 8259, section 9). Python converts at most 4,300 digits
    # between text and int, so a longer integer is a usage error before loading, not a traceback.
    rejected("has_item", "value=" + "1" + "0" * 5000)


@pytest.mark.parametrize(
    ("option", "argument"),
    [("has_item", "value=" + "[" * 100000 + "]" * 100000), ("regex", "value=" + "(" * 5000 + ")" * 5000)],
    ids=["has-item", "regex"],
)
def test_deeply_nested_values_never_crash(option, argument):
    # Unspecified: JSON parsers may limit nesting depth (RFC 8259, section 9) and the specification
    # sets no limit. Whether Python accepts this depth depends on its version (3.14 parses it), so a
    # too-deep value is either accepted or a usage error, never a crash.
    try:
        compile_filters(("value", "other"), {option: (argument,)})
    except click.UsageError:
        pass


# ---------------------------------------------------------------------------------------------
# Object keys: KEY is plain text, compared exactly.

OBJECTS = [
    {"a": 1},  # 0
    {"a": None},  # 1: the key is there even with a null value
    {"A": 1},  # 2
    {"ab": 1},  # 3
    {"b": {"a": 1}},  # 4: nested keys do not count
    {},  # 5
    {"": 0},  # 6
    {"a=b": 1},  # 7
    {" a": 1},  # 8
    {'"a"': 1},  # 9
    {"é": 1},  # 10
    {"É": 1},  # 11
    ["a"],  # 12: an array
    "a",  # 13: text
    '{"a": 1}',  # 14: text holding JSON
    None,  # 15
    [{"a": 1}],  # 16: an array of objects
    1,  # 17
]
HAS_KEY = [
    ("a", [0, 1]),
    ("A", [2]),
    ("ab", [3]),
    ("b", [4]),
    ("", [6]),  # FIELD= asks for the empty key
    ("a=b", [7]),
    (" a", [8]),
    ('"a"', [9]),  # not JSON: the quotes are part of the key
    ("é", [10]),
    ("É", [11]),
    ("zzz", []),
]


@pytest.mark.parametrize(("key", "expected"), HAS_KEY, ids=[case[0] or "empty" for case in HAS_KEY])
def test_has_key_finds_exact_keys_of_objects_only(key, expected):
    assert kept("has_key", "value=" + key, OBJECTS) == expected


# ---------------------------------------------------------------------------------------------
# Composition and validation when compiled.


def test_repeated_and_older_filters_combine_with_and():
    values = ["FIC.TO", "FIC.V", "fic.to", "OTHER.TO", "FICB.TO", None, "FIC"]
    assert kept_by({"regex": ("value=^FIC", r"value=\.TO$")}, values) == [0, 4]
    assert kept_by({"iglob": ("value=fic*",), "not_glob": ("value=FIC*",)}, values) == [2]
    assert kept_by({"contains_any": ('value=["to"]',), "contains_all": ('value=["fic", "b"]',)}, values) == [4]
    assert kept_by({"regex": ("value=^FIC",), "ine": ("value=fic.v",), "max_length": ("value=6",)}, values) == [0, 6]
    assert kept_by({"not_regex": (r"value=\.",), "nonempty": ("value",)}, values) == [6]
    assert kept_by({"iglob": ("value=*.to",), "not_in": ('value=["OTHER.TO"]',), "glob": ("value=*B*",)}, values) == [4]


def test_conditions_on_two_fields_combine_with_and():
    predicate = compile_filters(
        ("symbol", "date", "tags", "detail"),
        {
            "regex": (r"symbol=\.TO$",),
            "date_from": ("date=2024-01-01",),
            "has_item": ('tags="core"',),
            "has_key": ("detail=note",),
            "gt": ("detail=0",),  # an object is never a number, so this older filter rules out every row
        },
    )
    row = {"symbol": "FIC.TO", "date": "2024-02-01", "tags": ["core"], "detail": {"note": ""}}
    assert not predicate(row)
    predicate = compile_filters(
        ("symbol", "date", "tags", "detail"),
        {"regex": (r"symbol=\.TO$",), "date_from": ("date=2024-01-01",), "has_item": ('tags="core"',)},
    )
    assert predicate(row)
    assert not predicate({**row, "symbol": "FIC.V"})
    assert not predicate({**row, "date": "2023-12-31"})
    assert not predicate({**row, "tags": ["Core"]})


@pytest.mark.parametrize("option", OPTIONS)
def test_missing_equals_or_unknown_field_is_rejected_when_compiled(option):
    name = key_of(option)
    rejected(name, "value")
    assert "nope" in rejected(name, "nope=" + VALID[option])
    assert "Value" in rejected(name, "Value=" + VALID[option])  # field names are case-sensitive
    rejected(name, "=" + VALID[option])


@pytest.mark.xfail(
    strict=True,
    raises=ValueError,
    reason=(
        "#145: the report text convention is json.dumps(value, ensure_ascii=False, sort_keys=True), which writes "
        "NaN and Infinity, but the text filters serialize with allow_nan=False and raise ValueError (a traceback)"
    ),
)
def test_text_filters_read_non_finite_floats_by_the_report_text_convention():
    # JSON has no NaN, so saved data should never hold one; if a cell does, filters must not crash.
    values = [math.nan, math.inf, -math.inf, "x"]
    assert kept("regex", "value=^(NaN|-?Infinity)$", values) == [0, 1, 2]
    assert kept("not_regex", "value=x", values) == [0, 1, 2]
    assert kept("iglob", "value=*inf*", values) == [1, 2]
    assert kept("not_glob", "value=x", values) == [0, 1, 2]
    assert kept("contains_any", 'value=["nan"]', values) == [0]
    assert kept("contains_all", 'value=["-", "inf"]', values) == [2]


# ---------------------------------------------------------------------------------------------
# Through `report` and `summarize`.

MIXED = [
    ("FIC.TO", "2024-03-05"),  # 0
    ("fic.v", "2024-03-05T10:00:00"),  # 1
    ("Other", ["FIC.TO", 1]),  # 2: value text ["FIC.TO", 1]
    ("FICB.TO", {"symbol": "FIC.TO", "qty": 2}),  # 3: value text {"qty": 2, "symbol": "FIC.TO"}
    (None, None),  # 4
    ("MADEUP", 1.5),  # 5
    ("fictional", True),  # 6
    ("FIC.NE", "2024-03-06 09:00"),  # 7
]
# Arguments, then the positions in MIXED of the rows they keep.
EACH_FILTER = [
    (["--regex", "key=^FIC"], [0, 3, 7]),
    (["--not-regex", "key=(?i)^fic"], [2, 4, 5]),
    (["--iglob", "key=fic*"], [0, 1, 3, 6, 7]),
    (["--not-glob", "key=FIC*"], [1, 2, 4, 5, 6]),
    (["--contains-any", 'value=["fic.to", "TRUE"]'], [2, 3, 6]),
    (["--contains-all", 'value=["fic.to", "2"]'], [3]),
    (["--date-from", "value=2024-03-06"], [7]),
    (["--date-to", "value=2024-03-05"], [0, 1]),
    (["--has-item", 'value="FIC.TO"'], [2]),
    (["--has-key", "value=symbol"], [3]),
]


@pytest.mark.parametrize(("arguments", "expected"), EACH_FILTER, ids=[case[0][0] for case in EACH_FILTER])
def test_each_filter_through_report_and_summarize(monkeypatch, arguments, expected):
    rows = serve(monkeypatch, MIXED)
    before = json.dumps(rows)
    # JSON text keeps true apart from 1 and 1 apart from 1.0.
    assert json.dumps(output(report(*arguments))) == json.dumps([rows[position] for position in expected])
    assert report(*arguments, "--count").output == f"{len(expected)}\n"
    result = summarize(*arguments, "--metric", "rows=count", "--metric", "keys=values:key")
    assert output(result) == [{"rows": len(expected), "keys": [MIXED[position][0] for position in expected]}]
    assert json.dumps(rows) == before  # saved values are never modified


REPEATED = [
    (["--regex", "key=^F", "--regex", "key=TO$"], [0, 3]),
    (["--not-regex", "key=^F", "--not-regex", "key=^$"], [1, 2, 5, 6]),
    (["--iglob", "key=f*", "--iglob", "key=*E"], [7]),
    (["--not-glob", "key=FIC*", "--not-glob", "key=fic*"], [2, 4, 5]),
    (["--contains-any", 'value=["fic"]', "--contains-any", 'value=["qty", "zzz"]'], [3]),
    (["--contains-all", 'key=["fic"]', "--contains-all", 'key=[".", "o"]'], [0, 3]),
    (["--date-from", "value=2024-03-05", "--date-from", "value=2024-03-06"], [7]),
    (["--date-to", "value=2024-12-31", "--date-to", "value=2024-03-05"], [0, 1]),
    (["--has-item", 'value="FIC.TO"', "--has-item", "value=1.0"], [2]),
    (["--has-key", "value=symbol", "--has-key", "value=qty"], [3]),
    (["--has-key", "value=symbol", "--has-key", "value=nope"], []),
]
WITH_OLDER = [
    (["--regex", "key=^FIC", "--where", "value=2024-03-05"], [0]),
    (["--iglob", "key=FIC*", "--ieq", "value=2024-03-05t10:00:00"], [1]),
    (["--date-from", "value=2024-03-01", "--not-in", 'key=["FIC.TO"]'], [1, 7]),
    (["--contains-any", 'value=["fic"]', "--is-type", "value=array"], [2]),
    (["--not-regex", "key=^F", "--gt", "value=1"], [5]),
    (["--in", 'key=["Other", "MADEUP"]', "--not-glob", "value=1*"], [2]),
    (["--has-key", "value=qty", "--glob", "key=*B*"], [3]),
    (["--contains-all", 'key=["f", "c"]', "--max-length", "key=6", "--date-to", "value=2024-12-31"], [0, 1, 7]),
]


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize(
    ("arguments", "expected"), REPEATED + WITH_OLDER, ids=[" ".join(case[0]) for case in REPEATED + WITH_OLDER]
)
def test_repeated_and_older_filters_combine_with_and_on_both_commands(monkeypatch, command, arguments, expected):
    serve(monkeypatch, MIXED)
    assert kept_keys(command, *arguments) == [MIXED[position][0] for position in expected]


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (["--present", "key", "--iglob", "value=2024-03-0?*"], [0, 1, 7]),
        (["--missing", "key", "--regex", "value=^$"], [4]),
        (["--contains", "key=IC", "--not-regex", "value=^2024"], [3, 6]),
        (["--prefix", "key=oth", "--has-item", "value=1"], [2]),
        (["--suffix", "key=.to", "--contains-any", 'value=["qty"]'], [3]),
        (["--not", "key=FIC.TO", "--date-from", "value=2024-01-01"], [1, 7]),
    ],
    ids=["present", "missing", "contains", "prefix", "suffix", "not"],
)
def test_report_only_filters_combine_with_the_new_ones(monkeypatch, arguments, expected):
    serve(monkeypatch, MIXED)
    assert kept_keys("report", *arguments) == [MIXED[position][0] for position in expected]


@pytest.mark.parametrize("command", COMMANDS)
def test_empty_lists_and_empty_patterns_through_both_commands(monkeypatch, command):
    serve(monkeypatch, MIXED)
    keys = [key for key, _ in MIXED]
    assert kept_keys(command, "--contains-any", "value=[]") == []
    assert kept_keys(command, "--contains-all", "value=[]") == keys
    assert kept_keys(command, "--regex", "key=") == keys
    assert kept_keys(command, "--not-regex", "key=") == []
    assert kept_keys(command, "--iglob", "key=") == [None]
    assert kept_keys(command, "--not-glob", "key=") == [key for key in keys if key is not None]


@pytest.mark.parametrize("command", COMMANDS)
def test_only_the_first_equals_sign_separates_field_and_value(monkeypatch, command):
    serve(monkeypatch, [("eq", "a=b"), ("plain", "ab"), ("map", {"a=b": 1}), ("list", ["a=b"]), ("upper", "A=B=C")])
    cases = [
        (["--regex", "value=^a=b$"], ["eq"]),
        (["--regex", "value=="], ["eq", "map", "list", "upper"]),
        (["--not-regex", "value=a=b"], ["plain", "upper"]),
        (["--iglob", "value=a=b*"], ["eq", "upper"]),
        (["--not-glob", "value=*=*"], ["plain"]),
        (["--contains-any", 'value=["=B="]'], ["upper"]),
        (["--contains-all", 'value=["a=", "=b"]'], ["eq", "map", "list", "upper"]),
        (["--has-item", 'value="a=b"'], ["list"]),
        (["--has-key", "value=a=b"], ["map"]),
    ]
    for arguments, expected in cases:
        assert kept_keys(command, *arguments) == expected, arguments


@pytest.mark.parametrize("command", COMMANDS)
def test_date_range_through_both_commands(monkeypatch, command):
    serve(monkeypatch, [(f"d{position}", value) for position, value in enumerate(DATES)])
    arguments = ["--date-from", "value=2024-03-05", "--date-to", "value=2024-12-31"]
    assert kept_keys(command, *arguments) == ["d1", "d2", "d4", "d5", "d6", "d7", "d8"]


@pytest.mark.parametrize("command", COMMANDS)
def test_a_range_that_ends_before_it_starts_keeps_nothing(monkeypatch, command):
    # Unspecified: the specification lists no error for --date-from after --date-to (unlike --between,
    # which rejects LOW > HIGH). The implementation accepts the pair, exits 0 and keeps no rows.
    serve(monkeypatch, [(f"d{position}", value) for position, value in enumerate(DATES)])
    assert kept_keys(command, "--date-from", "value=2024-03-06", "--date-to", "value=2024-03-05") == []


def test_filters_set_the_count_and_page_total(monkeypatch):
    serve(monkeypatch, MIXED)
    assert report("--iglob", "key=fic*", "--not-glob", "key=*.TO", "--count").output == "3\n"
    result = report("--regex", "key=^FIC", "--page-info", "--offset", "1", "--limit", "1")
    assert output(result) == {
        "source": "config",
        "total": 3,
        "offset": 1,
        "limit": 1,
        "rows": [{"key": "FICB.TO", "value": {"symbol": "FIC.TO", "qty": 2}}],
    }


def test_filters_run_before_keyed_selection(monkeypatch):
    serve(monkeypatch, [("a", "x1"), ("a", "y2"), ("b", "y3"), ("b", "y4")])
    # Filtering first leaves a/y2, b/y3 and b/y4, so --unique keeps a/y2 and b/y3 (not just b/y3).
    assert [row["value"] for row in output(report("--regex", "value=^y", "--unique", "key"))] == ["y2", "y3"]
    # Among the filtered rows only b repeats, so a/y2 is not a duplicate.
    assert [row["value"] for row in output(report("--iglob", "value=Y*", "--duplicates", "key"))] == ["y3", "y4"]


def test_summarize_filters_source_rows_before_grouping_and_totals(monkeypatch):
    currencies = [
        ("FIC.TO", "CAD"),
        ("FIC.V", "CAD"),
        ("OTHER.TO", "CAD"),
        ("FIC.U", "USD"),
        ("MADEUP", "USD"),
        ("FICX", None),
    ]
    serve(monkeypatch, currencies)
    result = summarize(
        *("--regex", r"key=^FIC\.", "--group-by", "value", "--sort", "value", "--totals"),
        *("--metric", "rows=count", "--metric", "keys=values:key"),
    )
    # The closing row covers the three filtered rows, not the six saved ones.
    assert output(result) == [
        {"value": "CAD", "rows": 2, "keys": ["FIC.TO", "FIC.V"]},
        {"value": "USD", "rows": 1, "keys": ["FIC.U"]},
        {"value": None, "rows": 3, "keys": ["FIC.TO", "FIC.V", "FIC.U"]},
    ]
    result = summarize("--has-key", "value=x", "--group-by", "value", "--metric", "rows=count")
    assert output(result) == []


# ---------------------------------------------------------------------------------------------
# Derived columns are ordinary fields for every filter.

DERIVED_ROWS = [
    ("a", "2024-03-05"),
    ("b", "1999-12-31"),
    ("c", "n/a"),
    ("d", "2020-01-01T00:00"),
    ("e", None),
    ("f", ["FIC.TO"]),
    ("g", {"Symbol": "FIC.TO"}),
]
# year: 2024, 1999, null, 2020 and null after that. type: string four times, null, array, object.
# coalesce passes every value but null through unchanged, the array and the object included.
DERIVED = [
    (["--derive", "y=year:value", "--regex", "y=^202"], ["a", "d"]),
    (["--regex", "y=^202", "--derive", "y=year:value"], ["a", "d"]),  # option order does not matter
    (["--derive", "y=year:value", "--not-regex", "y=^202"], ["b", "c", "e", "f", "g"]),
    (["--derive", "d=date:value", "--date-to", "d=2020-01-01"], ["b", "d"]),
    (["--derive", "d=date:value", "--date-from", "d=2020-01-01"], ["a", "d"]),
    (["--derive", "kind=type:value", "--contains-any", 'kind=["NULL", "obj"]'], ["e", "g"]),
    (["--derive", "kind=type:value", "--contains-all", 'kind=["r", "a"]'], ["f"]),
    (["--derive", "kind=type:value", "--iglob", "kind=*R*"], ["a", "b", "c", "d", "f"]),
    (["--derive", "kind=type:value", "--not-glob", "kind=s*"], ["e", "f", "g"]),
    (["--derive", "same=coalesce:value:0", "--has-item", 'same="FIC.TO"'], ["f"]),
    (["--derive", "same=coalesce:value:0", "--has-key", "same=Symbol"], ["g"]),
]


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize(("arguments", "expected"), DERIVED, ids=[" ".join(case[0][2:]) for case in DERIVED])
def test_filters_read_derived_columns(monkeypatch, command, arguments, expected):
    serve(monkeypatch, DERIVED_ROWS)
    assert kept_keys(command, *arguments) == expected


def test_summarize_groups_rows_kept_by_a_filter_on_a_derived_column(monkeypatch):
    serve(monkeypatch, DERIVED_ROWS)
    result = summarize(
        "--derive", "y=year:value", "--iglob", "y=20??", "--group-by", "y", "--metric", "rows=count", "--sort", "y"
    )
    assert json.dumps(output(result)) == json.dumps([{"y": 2020, "rows": 1}, {"y": 2024, "rows": 1}])


# ---------------------------------------------------------------------------------------------
# Usage errors, all raised before the source is loaded.

MISSING_EQUALS = [[option, "value"] for option in OPTIONS]
UNKNOWN_FIELD = [[option, "nope=" + value] for option, value in VALID.items()]
INVALID_VALUE = [
    ["--regex", "value=("],
    ["--not-regex", "value=a{2,1}"],
    ["--regex", "value=a(?i)b"],
    ["--contains-any", "value=[1]"],
    ["--contains-all", 'value="x"'],
    ["--contains-any", "value="],
    ["--contains-all", "value=[x]"],
    ["--date-from", "value=2024-02-30"],
    ["--date-to", "value=2024-01-01T00:00"],
    ["--date-from", "value="],
    ["--date-to", "value=2024-1-1"],
    ["--has-item", "value=NaN"],
    ["--has-item", "value=Infinity"],
    ["--has-item", "value=1e999"],
    ["--has-item", "value=[1e999]"],
    ["--has-item", "value="],
    ["--has-item", "value=[1,"],
]


def invoke(command, *arguments):
    metric = ["--metric", "rows=count"] if command == "summarize" else []
    return CliRunner().invoke(main, [command, "config", *metric, *arguments])


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("arguments", MISSING_EQUALS, ids=[case[0] for case in MISSING_EQUALS])
def test_missing_equals_is_a_usage_error_before_loading(unloaded, command, arguments):
    result = invoke(command, *arguments)
    assert result.exit_code == 2, result.output


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("arguments", UNKNOWN_FIELD, ids=[case[0] for case in UNKNOWN_FIELD])
def test_unknown_field_is_a_usage_error_before_loading(unloaded, command, arguments):
    result = invoke(command, *arguments)
    assert result.exit_code == 2, result.output
    assert "Unknown field 'nope'" in result.output


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("arguments", INVALID_VALUE, ids=[" ".join(case) for case in INVALID_VALUE])
def test_invalid_value_is_a_usage_error_before_loading(unloaded, command, arguments):
    result = invoke(command, *arguments)
    assert result.exit_code == 2, result.output
    assert "Error:" in result.output


@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("option", OPTIONS)
def test_describe_accepts_none_of_the_new_filters(unloaded, command, option):
    result = CliRunner().invoke(main, [command, "config", "--describe", option, "value=" + VALID[option]])
    assert result.exit_code == 2, result.output


# ---------------------------------------------------------------------------------------------
# Real fictional data.


@pytest.fixture
def fictional_ledger(tracker, monkeypatch):
    store = tracker.store
    tfsa = store.add_account(Account("Fictional TFSA", type=AccountType.TFSA, track_cash=True))
    rrsp = store.add_account(Account("Fictional RRSP", type=AccountType.RRSP))
    archived = store.add_account(Account("Fictional Archived", archived=True))
    for txn in (
        Transaction(tfsa.saved_id, TxnType.DEPOSIT, "2023-12-28", amount=5000, currency="CAD"),
        Transaction(tfsa.saved_id, TxnType.BUY, "2024-01-15", "FIC.TO", 10, 20, currency="CAD"),
        Transaction(tfsa.saved_id, TxnType.BUY, "2024-01-31", "FICB.V", 5, 8, currency="CAD"),
        Transaction(archived.saved_id, TxnType.BUY, "2024-02-01", "HIDDEN.TO", 1, 1, currency="CAD"),
        Transaction(rrsp.saved_id, TxnType.BUY, "2024-02-29", "FIC.TO", 4, 22, currency="CAD"),
        Transaction(tfsa.saved_id, TxnType.DIVIDEND, "2024-03-15", "FIC.TO", amount=12.5, currency="CAD"),
        Transaction(tfsa.saved_id, TxnType.SELL, "2024-03-28", "FICB.V", 5, 9, currency="CAD"),
        Transaction(rrsp.saved_id, TxnType.BUY, "2024-04-01", "MADEUP", 1, 100, currency="USD"),
        Transaction(rrsp.saved_id, TxnType.BUY, "2024-04-02", "FICX.NE", 2, 50, currency="CAD"),
    ):
        store.add_transaction(txn)
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    return store


def test_real_ledger_transactions_in_a_date_range_whose_symbol_matches(fictional_ledger, fake):
    changes = fictional_ledger._conn.total_changes
    # The archived account's HIDDEN.TO buy is in range and matches, but archived activity stays hidden.
    window = ["--date-from", "date=2024-01-01", "--date-to", "date=2024-03-31", "--regex", r"symbol=\.(TO|V)$"]
    result = CliRunner().invoke(
        main, ["report", "transactions", *window, "--sort", "date", "--fields", "date,account,type,symbol"]
    )
    assert output(result) == [
        {"date": "2024-01-15", "account": "Fictional TFSA", "type": "BUY", "symbol": "FIC.TO"},
        {"date": "2024-01-31", "account": "Fictional TFSA", "type": "BUY", "symbol": "FICB.V"},
        {"date": "2024-02-29", "account": "Fictional RRSP", "type": "BUY", "symbol": "FIC.TO"},
        {"date": "2024-03-15", "account": "Fictional TFSA", "type": "DIVIDEND", "symbol": "FIC.TO"},
        {"date": "2024-03-28", "account": "Fictional TFSA", "type": "SELL", "symbol": "FICB.V"},
    ]
    result = CliRunner().invoke(
        main,
        [
            *("summarize", "transactions", *window, "--not-glob", "type=DIV*", "--group-by", "symbol"),
            *("--metric", "rows=count", "--metric", "shares=number-sum:quantity", "--sort", "symbol"),
        ],
    )
    assert output(result) == [
        {"symbol": "FIC.TO", "rows": 2, "shares": "14"},
        {"symbol": "FICB.V", "rows": 2, "shares": "10"},
    ]
    assert fake.calls == []
    assert fictional_ledger._conn.total_changes == changes


def test_real_catalogs_by_array_item_and_pattern_without_saved_data(monkeypatch):
    monkeypatch.setattr(App, "tracker", property(lambda self: pytest.fail("a catalog report opened the tracker")))
    # Of these five sources, only two have a field named symbol.
    sources = "source=^(cash-flows|rooms|symbols|closed-positions|account-activity)$"
    result = CliRunner().invoke(
        main,
        ["report", "sources", "--has-item", 'fields="symbol"', "--regex", sources, "--sort", "source"],
    )
    assert [row["source"] for row in output(result)] == ["closed-positions", "symbols"]
    # The field lists of these four, as JSON text: only two name a first_date or last_date field.
    result = CliRunner().invoke(
        main,
        [
            *("summarize", "sources", "--contains-any", 'fields=["_DATE"]'),
            *("--regex", "source=^(cash-flows|closed-positions|account-activity|snapshot-classes)$"),
            *("--group-by", "source", "--metric", "rows=count", "--sort", "source"),
        ],
    )
    assert output(result) == [{"source": "account-activity", "rows": 1}, {"source": "closed-positions", "rows": 1}]


def test_regex_patterns_python_warns_about_compile_quietly():
    # "[[" is a valid pattern that Python's re module flags as possible future syntax; users see no warning.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert kept("regex", "value=^[[{]", ["[x", "{y", "z"]) == [0, 1]


def test_missing_value_errors_name_the_option_as_typed():
    # --in is stored as in_values internally; its message still names the option people type.
    assert rejected("in_values", "value") == "--in requires FIELD=VALUE."
    assert rejected("not_in", "value") == "--not-in requires FIELD=VALUE."
    assert rejected("has_item", "value") == "--has-item requires FIELD=VALUE."
