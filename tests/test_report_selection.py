"""Keyed row selection (--duplicates, --singletons, --unique-last) and the report processing order.

Expected rows are worked out by hand from the #143 specification, never by calling the selection
code. Keys are the canonical JSON of each cell: 1, 1.0, "1" and true are four keys, null and ""
are two, and an object's key order does not matter.
"""

import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports
from marketpulse.cli.base import App
from marketpulse.models import Account, AccountType, Transaction, TxnType

SELECTIONS = ("--duplicates", "--singletons", "--unique-last")


def _serve(monkeypatch, rows):
    """Serve fixed rows; the source name then only selects the schema (`config` is key, value)."""
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    return rows


def _pairs(monkeypatch, pairs):
    return _serve(monkeypatch, [{"key": key, "value": value} for key, value in pairs])


def _indexed(*keys):
    """(key, row index) pairs, so every row stays distinguishable in the output."""
    return [(key, index) for index, key in enumerate(keys)]


def _report(*args):
    result = CliRunner().invoke(main, ["report", *args])
    assert result.exit_code == 0, result.output
    return result.output


def _assert_rows(output, expected):
    # Plain JSON text keeps 1, 1.0 and true apart and shows column and object key order.
    assert json.dumps(json.loads(output)) == json.dumps(expected)


TYPED_KEYS = [
    1,
    1.0,
    "1",
    True,
    1,
    None,
    "",
    None,
    False,
    0,
    "true",
    0.0,
    -0.0,
    "\N{LATIN SMALL LETTER E WITH ACUTE}",
    "e\N{COMBINING ACUTE ACCENT}",  # the same letter spelled with a combining accent is different text
    "\N{LATIN SMALL LETTER E WITH ACUTE}",
    [1, {"a": 1, "b": 2}],
    [1, {"b": 2, "a": 1}],
    {"x": [1.0]},
    {"x": [1]},
    {"b": 1, "a": [2]},
    {"a": [2], "b": 1},
]
# Repeated keys: 1 (rows 0 and 4), null (5, 7), the precomposed letter (13, 15) and two values whose
# objects list their keys in a different order (16, 17 and 20, 21).
TYPED_EXPECTED = {
    "--duplicates": [0, 4, 5, 7, 13, 15, 16, 17, 20, 21],
    "--singletons": [1, 2, 3, 6, 8, 9, 10, 11, 12, 14, 18, 19],
    "--unique-last": [1, 2, 3, 4, 6, 7, 8, 9, 10, 11, 12, 14, 15, 17, 18, 19, 21],
}


@pytest.mark.parametrize("option", SELECTIONS)
def test_keys_are_the_canonical_json_of_the_cell(monkeypatch, option):
    rows = _pairs(monkeypatch, _indexed(*TYPED_KEYS))
    before = json.dumps(rows)
    # The kept row 17 is printed as saved, with its object keys in their original order.
    _assert_rows(_report("config", option, "key"), [rows[i] for i in TYPED_EXPECTED[option]])
    assert json.dumps(rows) == before


# Rows 6 and 7 join to the same text with a comma, and rows 8 and 9 to the same JSON text without a
# separator: only a true composite key keeps them apart.
COMPOSITE = [
    ("a", 1),
    ("a", 2),
    ("b", 1),
    ("a", 1),
    ("b", 1.0),
    ("b", 1),
    ("x,y", "z"),
    ("x", "y,z"),
    (12, 3),
    (1, 23),
    ("c", 1),
]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--duplicates", "key", "--duplicates", "value"], [0, 2, 3, 5]),
        (["--duplicates", "value", "--duplicates", "key"], [0, 2, 3, 5]),
        (["--singletons", "key", "--singletons", "value"], [1, 4, 6, 7, 8, 9, 10]),
        (["--singletons", "value", "--singletons", "key"], [1, 4, 6, 7, 8, 9, 10]),
        (["--unique-last", "key", "--unique-last", "value"], [1, 3, 4, 5, 6, 7, 8, 9, 10]),
        (["--unique-last", "value", "--unique-last", "key"], [1, 3, 4, 5, 6, 7, 8, 9, 10]),
        # One field alone selects differently from both composite keys.
        (["--duplicates", "key"], [0, 1, 2, 3, 4, 5]),
        (["--duplicates", "value"], [0, 2, 3, 5, 10]),
        (["--singletons", "value"], [1, 4, 6, 7, 8, 9]),
        (["--unique-last", "key"], [3, 5, 6, 7, 8, 9, 10]),
        # Unspecified: naming a field twice is accepted and adds nothing to the key.
        (["--duplicates", "key", "--duplicates", "key"], [0, 1, 2, 3, 4, 5]),
        (["--unique-last", "key", "--unique-last", "key"], [3, 5, 6, 7, 8, 9, 10]),
    ],
)
def test_repeated_options_build_a_composite_key(monkeypatch, args, expected):
    rows = _pairs(monkeypatch, COMPOSITE)
    _assert_rows(_report("config", *args), [rows[i] for i in expected])


@pytest.mark.parametrize(
    ("option", "expected"),
    [("--duplicates", [0, 1, 2, 4]), ("--singletons", [3]), ("--unique-last", [2, 3, 4])],
)
def test_kept_rows_stay_in_source_order(monkeypatch, option, expected):
    # Duplicates interleave instead of grouping by key, and the last "b" (row 2) precedes the last
    # "a" (row 4) although "a" first appears before "c".
    rows = _pairs(monkeypatch, _indexed("b", "a", "b", "c", "a"))
    _assert_rows(_report("config", option, "key"), [rows[i] for i in expected])


@pytest.mark.parametrize(
    ("keys", "option", "expected"),
    [
        (["a", "b", "c"], "--duplicates", []),
        (["a", "b", "c"], "--singletons", [0, 1, 2]),
        (["a", "b", "c"], "--unique-last", [0, 1, 2]),
        (["a", "a", "a"], "--duplicates", [0, 1, 2]),
        (["a", "a", "a"], "--singletons", []),
        (["a", "a", "a"], "--unique-last", [2]),
    ],
)
def test_all_unique_and_all_duplicate_inputs(monkeypatch, keys, option, expected):
    rows = _pairs(monkeypatch, _indexed(*keys))
    _assert_rows(_report("config", option, "key"), [rows[i] for i in expected])


@pytest.mark.parametrize("option", SELECTIONS)
def test_empty_source(monkeypatch, option):
    _serve(monkeypatch, [])
    assert _report("config", option, "key") == "[]\n"
    assert _report("config", option, "key", "--count") == "0\n"
    assert json.loads(_report("config", option, "key", "--page-info")) == {
        "source": "config",
        "total": 0,
        "offset": 0,
        "limit": None,
        "rows": [],
    }
    assert _report("config", option, "key", "--format", "text") == "key  value\n---  -----\n"
    assert _report("config", option, "key", "--format", "records") == ""
    assert _report("config", option, "key", "--format", "lines", "--fields", "key") == ""
    assert _report("config", option, "key", "--format", "json-columns") == '{"key": [], "value": []}\n'
    assert _report("config", option, "key", "--format", "html") == (
        "<table>\n<thead>\n<tr><th>key</th><th>value</th></tr>\n</thead>\n<tbody>\n</tbody>\n</table>\n"
    )


# Each removes row 1 only: the older --not and --ine, and the newer --not-regex, --not-glob and
# --contains-any.
WITHOUT_ROW_1 = [
    ["--not", "value=drop"],
    ["--ine", "value=DROP"],
    ["--not-regex", "value=^drop$"],
    ["--not-glob", "value=d*"],
    ["--contains-any", 'value=["KEEP"]'],
]


@pytest.mark.parametrize("filter_args", WITHOUT_ROW_1, ids=[args[0] for args in WITHOUT_ROW_1])
@pytest.mark.parametrize(
    ("option", "expected"), [("--duplicates", [2, 3]), ("--singletons", [0]), ("--unique-last", [0, 3])]
)
def test_selection_sees_only_the_filtered_rows(monkeypatch, filter_args, option, expected):
    # Without row 1, row 0 is the only "a": not a duplicate, a singleton, and the last "a". Selecting
    # before filtering would give [0, 2, 3], [] and [3].
    rows = _pairs(monkeypatch, [("a", "keep"), ("a", "drop"), ("b", "keep"), ("b", "keep too")])
    _assert_rows(_report("config", *filter_args, option, "key"), [rows[i] for i in expected])


# id: (key, value) rows, arguments, the rows kept, and the rows kept if the two steps were swapped.
ORDER_CASES = {
    # Step 3 before step 4: --duplicates and --singletons choose rows before --unique and --unique-last,
    # whatever the argument order.
    "duplicates-unique": ([("a", 1), ("b", 1), ("b", 2)], ["--duplicates", "key", "--unique", "value"], [1, 2], []),
    "argument-order": ([("a", 1), ("b", 1), ("b", 2)], ["--unique", "value", "--duplicates", "key"], [1, 2], []),
    "duplicates-unique-last": (
        [("a", 1), ("a", 2), ("b", 1)],
        ["--duplicates", "key", "--unique-last", "value"],
        [0, 1],
        [],
    ),
    "singletons-unique": ([("a", 1), ("b", 1), ("b", 2)], ["--singletons", "key", "--unique", "value"], [0], [0, 2]),
    "singletons-unique-last": (
        [("a", 1), ("b", 1), ("b", 2)],
        ["--singletons", "key", "--unique-last", "value"],
        [0],
        [],
    ),
    # Step 4 before step 5: the last row per key is the last in source order, not in sorted order.
    # Which rows --duplicates and --singletons keep never depends on row order.
    "unique-last-sort": ([("a", 3), ("a", 1), ("b", 2)], ["--unique-last", "key", "--sort", "value"], [1, 2], [2, 0]),
    "unique-last-sort-ci": (
        [("a", "b"), ("a", "A"), ("b", "C")],
        ["--unique-last", "key", "--sort-ci", "value"],
        [1, 2],
        [0, 2],
    ),
    # Steps 3 and 4 before step 6.
    "unique-last-reverse-rows": (_indexed("a", "b", "a"), ["--unique-last", "key", "--reverse-rows"], [2, 1], [1, 0]),
    "duplicates-tail": (_indexed("a", "a", "b", "c"), ["--duplicates", "key", "--tail", "2"], [0, 1], []),
    "singletons-tail": (_indexed("a", "b", "a"), ["--singletons", "key", "--tail", "1"], [1], [2]),
    "unique-last-tail": (_indexed("a", "b", "b"), ["--unique-last", "key", "--tail", "2"], [0, 2], [2]),
    "duplicates-every": (_indexed("a", "a", "b", "b"), ["--duplicates", "key", "--every", "2"], [0, 2], []),
    "singletons-every": (_indexed("a", "b", "a", "c", "d"), ["--singletons", "key", "--every", "2"], [1, 4], [4]),
    "unique-last-every": (_indexed("a", "a", "b", "c"), ["--unique-last", "key", "--every", "2"], [1, 3], [0, 2]),
    # Steps 3 and 4 before step 8.
    "duplicates-page": (_indexed("x", "a", "a"), ["--duplicates", "key", "--offset", "1", "--limit", "1"], [2], []),
    "singletons-page": (
        _indexed("a", "a", "b", "c"),
        ["--singletons", "key", "--offset", "1", "--limit", "1"],
        [3],
        [1],
    ),
    "unique-last-page": (_indexed("a", "b", "a"), ["--unique-last", "key", "--offset", "1", "--limit", "1"], [2], [1]),
}


@pytest.mark.parametrize(("pairs", "args", "expected", "swapped"), ORDER_CASES.values(), ids=ORDER_CASES.keys())
def test_selection_runs_between_filters_and_row_windows(monkeypatch, pairs, args, expected, swapped):
    # Every case tells the two orders apart.
    assert swapped != expected
    rows = _pairs(monkeypatch, pairs)
    _assert_rows(_report("config", *args), [rows[i] for i in expected])


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        # One row for each repeated key: the first, or the last.
        (["--duplicates", "key", "--unique", "key"], [0, 1]),
        (["--duplicates", "key", "--unique-last", "key"], [2, 4]),
        (["--singletons", "key", "--unique", "key"], [3]),
        (["--singletons", "key", "--unique-last", "key"], [3]),
        (["--duplicates", "key", "--sort", "value"], [2, 0, 4, 1]),
        (["--duplicates", "key", "--unique-last", "key", "--sort", "value", "--descending"], [4, 2]),
        (["--singletons", "value", "--unique-last", "key"], [2, 3, 4]),
    ],
)
def test_allowed_combinations(monkeypatch, args, expected):
    rows = _pairs(monkeypatch, [("a", 3), ("b", 9), ("a", 1), ("c", 0), ("b", 5)])
    _assert_rows(_report("config", *args), [rows[i] for i in expected])


@pytest.mark.parametrize(
    ("args", "total", "page"),
    [
        ([], 6, [1]),
        (["--duplicates", "key"], 5, [1]),
        (["--singletons", "key"], 1, []),
        (["--unique-last", "key"], 3, [4]),
        (["--unique", "key"], 3, [1]),
        (["--duplicates", "key", "--unique", "key"], 2, [1]),
        (["--duplicates", "key", "--unique-last", "key"], 2, [5]),
        (["--singletons", "key", "--unique-last", "key"], 1, []),
    ],
)
def test_selection_changes_count_and_page_total(monkeypatch, args, total, page):
    rows = _pairs(monkeypatch, _indexed("a", "b", "a", "c", "a", "b"))
    assert _report("config", *args, "--count") == f"{total}\n"
    # The total is counted before --offset and --limit take the second row.
    payload = json.loads(_report("config", *args, "--offset", "1", "--limit", "1", "--page-info"))
    assert payload == {"source": "config", "total": total, "offset": 1, "limit": 1, "rows": [rows[i] for i in page]}


@pytest.mark.parametrize(
    ("args", "numbered"),
    [
        (["--duplicates", "key"], [(0, 1), (2, 2)]),
        (["--singletons", "key"], [(1, 1), (3, 2)]),
        (["--unique-last", "key"], [(1, 1), (2, 2), (3, 3)]),
        (["--singletons", "key", "--offset", "1"], [(3, 2)]),
    ],
)
def test_row_numbers_count_the_selected_rows(monkeypatch, args, numbered):
    # Numbering the source rows instead would give 1, 3 for the duplicates and 2, 4 for the singletons.
    rows = _pairs(monkeypatch, _indexed("a", "b", "a", "c"))
    expected = [{**rows[i], "n": number} for i, number in numbered]
    _assert_rows(_report("config", *args, "--row-number", "n"), expected)


DATES = [
    "2024-01-05",
    "2024-01-20T09:30:00",
    "2024-02-01",
    "2024-03-01 10:00",
    "2024-03-31",
    "pending",
    None,
    "2024-02-30",
]
# year-month of each value: text that is not a real calendar date gives null, and null is a key too.
MONTHS = ["2024-01", "2024-01", "2024-02", "2024-03", "2024-03", None, None, None]


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["--duplicates", "m"], [0, 1, 3, 4, 5, 6, 7]),
        (["--singletons", "m"], [2]),
        (["--unique-last", "m"], [1, 2, 4, 7]),
        # Filters on derived and source values run first.
        (["--present", "m", "--duplicates", "m"], [0, 1, 3, 4]),
        (["--not-regex", "value=T", "--duplicates", "m"], [3, 4, 5, 6, 7]),
        (["--date-from", "value=2024-02-01", "--unique-last", "m"], [2, 4]),
    ],
)
def test_derived_column_as_the_key(monkeypatch, args, expected):
    rows = _pairs(monkeypatch, [(f"k{index}", value) for index, value in enumerate(DATES)])
    output = _report("config", "--derive", "m=year-month:value", *args)
    _assert_rows(output, [{**rows[i], "m": MONTHS[i]} for i in expected])
    # Derived columns exist before any key is read, wherever --derive appears among the arguments.
    assert _report("config", *args, "--derive", "m=year-month:value") == output


def test_selection_reads_saved_values_before_output_transforms(monkeypatch):
    _pairs(monkeypatch, _indexed("A", "a", "b", "b"))
    # --lower changes output only (step 9), so "A" and "a" are still two keys when rows are chosen.
    _assert_rows(
        _report("config", "--lower", "key", "--duplicates", "key"),
        [{"key": "b", "value": 2}, {"key": "b", "value": 3}],
    )
    # A derived column exists from step 1, so its lowercase text is the key.
    _assert_rows(
        _report("config", "--derive", "lk=lower:key", "--duplicates", "lk"),
        [
            {"key": "A", "value": 0, "lk": "a"},
            {"key": "a", "value": 1, "lk": "a"},
            {"key": "b", "value": 2, "lk": "b"},
            {"key": "b", "value": 3, "lk": "b"},
        ],
    )
    _pairs(monkeypatch, _indexed(None, "b"))
    _assert_rows(
        _report("config", "--fill", 'key="b"', "--singletons", "key"),
        [{"key": "b", "value": 0}, {"key": "b", "value": 1}],
    )
    _pairs(monkeypatch, _indexed("a", "b", "a"))
    _assert_rows(
        _report("config", "--rename", "key=name", "--unique-last", "key"),
        [{"name": "b", "value": 1}, {"name": "a", "value": 2}],
    )


def test_key_need_not_be_an_output_column(monkeypatch):
    _pairs(monkeypatch, _indexed("a", "b", "a"))
    _assert_rows(_report("config", "--duplicates", "key", "--fields", "value"), [{"value": 0}, {"value": 2}])
    _assert_rows(_report("config", "--singletons", "key", "--omit", "key"), [{"value": 1}])
    assert _report("config", "--unique-last", "key", "--fields", "value", "--format", "lines") == "1\n2\n"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--duplicates", "key", "--singletons", "value"], "Choose --duplicates or --singletons."),
        (["--singletons", "key", "--duplicates", "key"], "Choose --duplicates or --singletons."),
        (["--unique", "key", "--unique-last", "value"], "Choose --unique or --unique-last."),
        (["--unique-last", "key", "--unique", "key"], "Choose --unique or --unique-last."),
        # The specification gives no message for an unknown key field; this is the one --derive uses.
        (["--duplicates", "bogus"], "Unknown field 'bogus'. Choose from: key, value."),
        (["--singletons", "bogus"], "Unknown field 'bogus'. Choose from: key, value."),
        (["--unique-last", "bogus"], "Unknown field 'bogus'. Choose from: key, value."),
        (["--duplicates", "key", "--duplicates", "Key"], "Unknown field 'Key'."),
        # Unspecified: each option names one field, so a comma list is one unknown name, as with --unique.
        (["--duplicates", "key,value"], "Unknown field 'key,value'."),
        # Renames and row numbers come after selection, so their names are not keys.
        (["--rename", "key=name", "--singletons", "name"], "Unknown field 'name'."),
        (["--row-number", "n", "--unique-last", "n"], "Unknown field 'n'."),
        (["--describe", "--duplicates", "key"], "--describe"),
        (["--describe", "--singletons", "key"], "--describe"),
        (["--describe", "--unique-last", "key"], "--describe"),
        (["--describe", "--derive", "m=month:value", "--duplicates", "m"], "--describe"),
        # Unspecified precedence: an unknown field is reported before a conflict, and a conflict before
        # --describe.
        (["--duplicates", "bogus", "--singletons", "key"], "Unknown field 'bogus'."),
        (["--describe", "--unique", "key", "--unique-last", "key"], "Choose --unique or --unique-last."),
    ],
)
def test_invalid_selection_fails_before_loading(monkeypatch, args, message):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("invalid selection loaded a source"))
    result = CliRunner().invoke(main, ["report", "config", *args])
    assert result.exit_code == 2, result.output
    assert message in result.output


@pytest.mark.parametrize("option", SELECTIONS)
def test_summarize_has_no_keyed_selection(monkeypatch, option):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("summarize loaded a source"))
    result = CliRunner().invoke(main, ["summarize", "config", "--metric", "rows=count", option, "key"])
    assert result.exit_code == 2, result.output
    assert "No such option" in result.output and option in result.output


# flows rows: date, account_id, account, amount, currency.
FLOWS = [
    ("2024-01-05", 1, "Fictional Cash", 250, "CAD"),  # r0
    ("2024-01-09", 2, "Fictional TFSA", 75.5, "CAD"),  # r1
    ("2024-01-20", 3, "Fictional RRSP", 40, "USD"),  # r2
    ("2024-01-25", 2, "Fictional TFSA", 300, "CAD"),  # r3
    ("2024-02-01", 3, "Fictional RRSP", 280, "USD"),  # r4
    ("2024-02-14", 4, "Fictional Margin", 60, "USD"),  # r5
    ("2024-02-28", 2, "Fictional TFSA", 500, "CAD"),  # r6
    ("2024-02-29T10:00:00", 2, "Fictional TFSA", 125, "CAD"),  # r7
    ("2024-03-03", 2, "Fictional TFSA", 10, "CAD"),  # r8
    ("2024-03-07", 1, "Fictional Cash", 45, "CAD"),  # r9
    ("2024-03-08", 4, "Fictional margin", 70, "CAD"),  # r10
    ("2024-03-09", 3, "Fictional RRSP", 15, "USD"),  # r11
]
# Every step of the report processing order, worked by hand on FLOWS:
# 1. --derive month=year-month:date: 2024-01 for r0-r3, 2024-02 for r4-r7 (r7 is a timestamp),
#    2024-03 for r8-r11.
# 2. --not-regex 'account=(?i)margin' drops r5 and r10.
# 3. --duplicates month --duplicates currency: (01, CAD) r0 r1 r3 and (02, CAD) r6 r7 and (03, CAD)
#    r8 r9 repeat; r2, r4 and r11 are alone (r4 only because step 2 removed r5). Kept: r0 r1 r3 r6
#    r7 r8 r9.
# 4. --unique-last account --unique-last month: (Cash, 01) r0, (TFSA, 01) r3 over r1, (TFSA, 02) r7
#    over r6, (TFSA, 03) r8, (Cash, 03) r9. Kept in source order: r0 r3 r7 r8 r9.
# 5. --sort amount: r8 10, r9 45, r7 125, r0 250, r3 300.
# 6. --tail 4: r9 r7 r0 r3.
# 7. Total: 4.
# 8. --offset 1 --limit 2: r7 r0.
# 9. --upper account, --rename amount=value, --row-number n (positions 2 and 3).
# 10. --fields n,month,account,value.
# 11. --format text: numbers right-aligned in columns 1, 7, 14 and 5 characters wide.
# Swapping steps 2/3 would print r0 and r4, steps 3/4 r9 and r0, steps 4/5 r0 and r3, and
# steps 6/8 r9 and r7.
PIPELINE = [
    *("--derive", "month=year-month:date", "--not-regex", "account=(?i)margin"),
    *("--duplicates", "month", "--duplicates", "currency", "--unique-last", "account", "--unique-last", "month"),
    *("--sort", "amount", "--tail", "4"),
]
PAGE = [
    *("--offset", "1", "--limit", "2", "--upper", "account", "--rename", "amount=value"),
    *("--row-number", "n", "--fields", "n,month,account,value"),
]


def test_full_report_processing_order(monkeypatch):
    fields = ("date", "account_id", "account", "amount", "currency")
    rows = _serve(monkeypatch, [dict(zip(fields, flow, strict=True)) for flow in FLOWS])
    before = json.dumps(rows)
    assert _report("cash-flows", *PIPELINE, *PAGE, "--format", "text") == (
        "n  month    account         value\n"
        "-  -------  --------------  -----\n"
        "2  2024-02  FICTIONAL TFSA    125\n"
        "3  2024-01  FICTIONAL CASH    250\n"
    )
    assert json.loads(_report("cash-flows", *PIPELINE, *PAGE, "--page-info")) == {
        "source": "cash-flows",
        "total": 4,
        "offset": 1,
        "limit": 2,
        "rows": [
            {"n": 2, "month": "2024-02", "account": "FICTIONAL TFSA", "value": 125},
            {"n": 3, "month": "2024-01", "account": "FICTIONAL CASH", "value": 250},
        ],
    }
    assert _report("cash-flows", *PIPELINE, *PAGE, "--format", "json-columns") == (
        '{"n": [2, 3], "month": ["2024-02", "2024-01"], "account": ["FICTIONAL TFSA", "FICTIONAL CASH"], '
        '"value": [125, 250]}\n'
    )
    assert _report("cash-flows", *PIPELINE, "--count") == "4\n"
    assert json.dumps(rows) == before


@pytest.fixture
def ledger(tracker, monkeypatch):
    """Entries 1-8 in date order, then id. Entry 3 repeats entry 2; archived entry 7 would make entry 5
    a duplicate if archived activity were visible."""
    store = tracker.store
    cash = store.add_account(Account("Fictional Cash", track_cash=True)).saved_id
    tfsa = store.add_account(Account("Fictional TFSA", AccountType.TFSA)).saved_id
    archived = store.add_account(Account("Fictional Archived", AccountType.RRSP, archived=True)).saved_id
    for txn in (
        Transaction(cash, TxnType.DEPOSIT, "2024-01-02", amount=5000, currency="CAD"),  # 1
        Transaction(cash, TxnType.BUY, "2024-01-03", "FIC.TO", 10, 20, currency="CAD"),  # 2
        Transaction(cash, TxnType.BUY, "2024-01-03", "FIC.TO", 10, 20, currency="CAD"),  # 3
        Transaction(tfsa, TxnType.BUY, "2024-01-10", "FICB.TO", 5, 30, currency="CAD"),  # 4
        Transaction(cash, TxnType.SELL, "2024-02-01", "FIC.TO", 4, 22, currency="CAD"),  # 5
        Transaction(tfsa, TxnType.BUY, "2024-02-15", "FICB.TO", 5, 31, currency="CAD"),  # 6
        Transaction(archived, TxnType.BUY, "2024-02-01", "FIC.TO", 4, 22, currency="CAD"),  # 7
        Transaction(cash, TxnType.DIVIDEND, "2024-03-01", "FIC.TO", amount=3.5, currency="CAD"),  # 8
    ):
        store.add_transaction(txn)
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    return store


def test_fictional_ledger_latest_entries_and_possible_duplicates(ledger, fake):
    changes = ledger._conn.total_changes
    assert [row["id"] for row in json.loads(_report("transactions", "--fields", "id"))] == [1, 2, 3, 4, 5, 6, 8]
    # The latest entry per symbol; without --present the cash deposit's empty symbol is a key too.
    assert json.loads(
        _report("transactions", "--present", "symbol", "--unique-last", "symbol", "--fields", "id,date,symbol,type")
    ) == [
        {"id": 6, "date": "2024-02-15", "symbol": "FICB.TO", "type": "BUY"},
        {"id": 8, "date": "2024-03-01", "symbol": "FIC.TO", "type": "DIVIDEND"},
    ]
    assert json.loads(_report("transactions", "--unique-last", "symbol", "--fields", "id")) == [
        {"id": 1},
        {"id": 6},
        {"id": 8},
    ]
    # Entry 6 repeats entry 4's symbol and quantity on another day; entry 5's archived twin stays hidden.
    duplicates = ["--duplicates", "date", "--duplicates", "symbol", "--duplicates", "quantity"]
    _assert_rows(
        _report("transactions", *duplicates, "--fields", "id,account,date,symbol,quantity"),
        [
            {"id": 2, "account": "Fictional Cash", "date": "2024-01-03", "symbol": "FIC.TO", "quantity": 10.0},
            {"id": 3, "account": "Fictional Cash", "date": "2024-01-03", "symbol": "FIC.TO", "quantity": 10.0},
        ],
    )
    same_account = ["--duplicates", "account_id", *duplicates, "--fields", "id,date,account,symbol,quantity,price"]
    assert _report("transactions", *same_account, "--format", "text") == (
        "id  date        account         symbol  quantity  price\n"
        "--  ----------  --------------  ------  --------  -----\n"
        " 2  2024-01-03  Fictional Cash  FIC.TO      10.0   20.0\n"
        " 3  2024-01-03  Fictional Cash  FIC.TO      10.0   20.0\n"
    )
    # Entry types used once: the deposit, the sale and the dividend.
    assert json.loads(_report("transactions", "--singletons", "type", "--fields", "id")) == [
        {"id": 1},
        {"id": 5},
        {"id": 8},
    ]
    assert _report("transactions", *duplicates, "--unique-last", "symbol", "--count") == "1\n"
    assert fake.calls == []
    assert ledger._conn.total_changes == changes
