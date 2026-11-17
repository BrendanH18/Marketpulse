"""The seven summary operations added under #153, on every dataset, with expectations worked out by hand.

Nothing here calls the aggregation code to build an expected value. Fixed rows stand in for each
saved source (the source name only selects a schema), as in the earlier summary matrices.
"""

import json
import math

import click
import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports
from marketpulse.cli.report_metrics import ALL_OPERATIONS, FURTHER_OPERATIONS, summarize_values

# Operation, the first field's cells, and the result. Each comment shows the arithmetic.
CASES = [
    # Finite numbers -3, 0, 4, 7.5, 12, 30 (n = 6); rank 5 × 0.1 = 0.5, so -3 + 0.5 × (0 - -3).
    ("number-p10", [12, "-3", 7.5, "0", 30, True, "-Infinity", "x", {}, None, 4], "-1.5"),
    # The same numbers; rank 5 × 0.9 = 4.5, so 12 + 0.5 × (30 - 12).
    ("number-p90", [12, "-3", 7.5, "0", 30, True, "-Infinity", "x", {}, None, 4], "21"),
    # Sorted -5, 0, 10, 15.5, 20, 40: Q1 at rank 1.25 is 0 + 0.25 × 10 = 2.5; Q3 at rank 3.75 is
    # 15.5 + 0.75 × 4.5 = 18.875; their difference is 16.375.
    ("number-iqr", [10, "20", 15.5, "-5", 40, 0, True, "Infinity", "", [1], None], "16.375"),
    # 2, 4, 4, 4, 5, 5, 7, 9: mean 5, distances 3 + 1 + 1 + 1 + 0 + 0 + 2 + 4 = 12, over 8.
    ("number-mean-absolute-deviation", [2, "4", 4.0, "4", 5, 5, 7, 9, False, "NaN", None, "x"], "1.5"),
    # Eight cells, of which null and "" are missing: 6 / 8 = 75%.
    ("present-percent", [None, "", "a", 0, False, [], {}, " "], "75"),
    # 2024-03-01 (three spellings), 2024-02-29 and 2023-12-31; impossible dates, a date without
    # padding, a number, true, null and "" are not dates.
    (
        "date-distinct",
        [
            "2024-03-01",
            "2024-03-01T09:30:00",
            "2024-03-01 16:00",
            "2024-02-29",
            "2024-02-30",
            "2025-13-01",
            "2024-2-29",
            20240229,
            True,
            None,
            "",
            "2023-12-31",
        ],
        3,
    ),
    # Two strings of 14 characters; the first wins. The 15-item array and the number are not strings.
    (
        "longest-text",
        ["ab", None, "Fictional TFSA", 123456789012345, list("abcdefghijklmno"), "Fictional RRSP", "", "fictional"],
        "Fictional TFSA",
    ),
]


@pytest.mark.parametrize("source", sorted(reports.SOURCES))
@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_further_summary_matrix(monkeypatch, source, case):
    operation, values, expected = case
    schema = reports.SOURCES[source]
    field = schema[0]
    rows = [{**dict.fromkeys(schema), field: value} for value in values]
    before = json.dumps(rows)
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    result = CliRunner().invoke(main, ["summarize", source, "--metric", f"result={operation}:{field}"])
    assert result.exit_code == 0, result.output
    # Compare JSON text so a decimal string and a number, or 1 and true, stay apart.
    assert json.dumps(json.loads(result.output)) == json.dumps([{"result": expected}])
    assert json.dumps(rows) == before  # source rows are never modified


def test_inventory_is_seven_operations_on_fifty_seven_datasets():
    assert [case[0] for case in CASES] == list(FURTHER_OPERATIONS)
    assert len(FURTHER_OPERATIONS) == len(set(FURTHER_OPERATIONS)) == 7
    assert ALL_OPERATIONS[-7:] == FURTHER_OPERATIONS
    # Preserve the historical #153 inventory; #162 adds report-fields afterwards.
    earlier_sources = set(reports.SOURCES) - {"report-fields"}
    assert len(earlier_sources) == 57
    assert len(CASES) * len(earlier_sources) == 399


# Edge cases, straight on the summary function.


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("number-p10", None),
        ("number-p90", None),
        ("number-iqr", None),
        ("number-mean-absolute-deviation", None),
        ("present-percent", None),
        ("date-distinct", 0),
        ("longest-text", None),
    ],
)
def test_no_cells(operation, expected):
    assert summarize_values(operation, []) == expected


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("number-p10", None),
        ("number-p90", None),
        ("number-iqr", None),
        ("number-mean-absolute-deviation", None),
        ("present-percent", "0"),
        ("date-distinct", 0),
        # The empty string is still a string, as for text-min and string-count.
        ("longest-text", ""),
    ],
)
def test_all_missing_cells(operation, expected):
    assert summarize_values(operation, [None, "", None]) == expected


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        ("number-p10", None),
        ("number-p90", None),
        ("number-iqr", None),
        ("number-mean-absolute-deviation", None),
        ("present-percent", "100"),
        ("date-distinct", 0),
        ("longest-text", "-Infinity"),
    ],
)
def test_non_finite_cells_are_not_numbers(operation, expected):
    # Floats from saved data and numeric strings alike; booleans are never numbers.
    cells = [math.nan, math.inf, -math.inf, "NaN", "-Infinity", "Infinity", True, False]
    assert summarize_values(operation, cells) == expected


@pytest.mark.parametrize(
    ("operation", "expected"),
    [
        # Finite numbers -2 and 1.5: rank 0.1 gives -2 + 0.1 × 3.5; rank 0.9 gives -2 + 0.9 × 3.5.
        ("number-p10", "-1.65"),
        ("number-p90", "1.15"),
        # Q1 -2 + 0.25 × 3.5 = -1.125; Q3 -2 + 0.75 × 3.5 = 0.625.
        ("number-iqr", "1.75"),
        # Mean -0.25; both lie 1.75 away.
        ("number-mean-absolute-deviation", "1.75"),
    ],
)
def test_numbers_beside_non_finite_ones(operation, expected):
    assert summarize_values(operation, [math.nan, 1.5, math.inf, -2, -math.inf]) == expected


@pytest.mark.parametrize(
    ("operation", "cells", "expected"),
    [
        # One number is every quantile of itself and has no spread.
        ("number-p10", ["12.50"], "12.5"),
        ("number-p90", [-7], "-7"),
        ("number-iqr", [3.25], "0"),
        ("number-mean-absolute-deviation", ["1e30"], "0"),
        # 0 to 10 (n = 11): ranks 1 and 9 fall exactly on the values 1 and 9.
        ("number-p10", [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0], "1"),
        ("number-p90", [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0], "9"),
        # Q1 at rank 2.5 is 2.5 and Q3 at rank 7.5 is 7.5.
        ("number-iqr", [10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0], "5"),
        # Integers 1, 1.0 and "1.00" are one value; trailing zeros never show.
        ("number-p90", [1, "1.00", 1.0], "1"),
        # A value on a rank keeps its own exponent, however small.
        ("number-p10", ["1E-2000000"], "1E-2000000"),
        # 0.1 and 0.2, read by their decimal text: rank 0.1 gives 0.1 + 0.1 × 0.1, rank 0.9 gives 0.1 + 0.9 × 0.1.
        ("number-p10", [0.2, 0.1], "0.11"),
        ("number-p90", [0.2, 0.1], "0.19"),
        # 0, 0, 1: mean 1/3, distances 1/3 + 1/3 + 2/3 = 4/3, over 3 is 4/9, to 28 significant digits.
        ("number-mean-absolute-deviation", [0, 0, 1], "0.4444444444444444444444444444"),
        # Two numbers lie half their range from their mean: 1e20 here.
        ("number-mean-absolute-deviation", ["1e20", "-1e20"], "100000000000000000000"),
        # x / 2 for x = 10^28 + 1 and 10^28 + 3 has 29 significant digits ending in 5: ties go to even.
        ("number-mean-absolute-deviation", [0, 10**28 + 1], "5E+27"),
        ("number-mean-absolute-deviation", [0, 10**28 + 3], "5.000000000000000000000000002E+27"),
        # Shares: 1/3, 2/3 and 1/7 of the rows, to 28 significant digits.
        ("present-percent", ["x", None, ""], "33.33333333333333333333333333"),
        ("present-percent", [None, "x", "y"], "66.66666666666666666666666667"),
        ("present-percent", ["x", *[None] * 6], "14.28571428571428571428571429"),
        # Zero, false, whitespace and empty arrays or objects are present; only null and "" are missing.
        ("present-percent", [0, False, " ", [], {}], "100"),
        # A date-time counts as the calendar day it names, without converting time zones.
        ("date-distinct", ["2024-03-01T23:00:00-05:00", "2024-03-01T01:00:00+09:00", "2024-03-02"], 2),
        ("date-distinct", ["2024-03-01T24:00:00", "2024-03-01x", ["2024-03-01"]], 0),
        # Length counts characters (code points): a decomposed accent is two.
        ("longest-text", ["é", "é"], "é"),
        ("longest-text", [["much", "longer"], {"key": "value"}, "ab", "cd"], "ab"),
        ("longest-text", [1, True, None], None),
    ],
)
def test_worked_edge_cases(operation, cells, expected):
    assert summarize_values(operation, cells) == expected


@pytest.mark.parametrize("operation", ["number-p10", "number-p90", "number-iqr", "number-mean-absolute-deviation"])
def test_numeric_operations_keep_the_working_digit_limit(operation):
    # 1e5000 and 1e-5001 span 10,002 digits, beyond the 10,000 the other numeric summaries allow.
    with pytest.raises(click.ClickException, match="more than 10,000 decimal digits"):
        summarize_values(operation, ["1e5000", "1e-5001"])


def test_many_cells_stay_fast_and_exact():
    # 0 to 99,999, then its reverse: no quadratic scans, and every result is exact. Sorted, rank i holds i // 2.
    numbers = [*range(100_000), *range(99_999, -1, -1)]
    # 199,999 × 0.1 = 19,999.9: rank 19,999 holds 9,999 and the next 10,000, so 9,999.9.
    assert summarize_values("number-p10", numbers) == "9999.9"
    # 199,999 × 0.9 = 179,999.1: rank 179,999 holds 89,999 and the next 90,000, so 89,999.1.
    assert summarize_values("number-p90", numbers) == "89999.1"
    # Q1 at rank 49,999.75 is 24,999.75; Q3 at rank 149,999.25 is 74,999.25.
    assert summarize_values("number-iqr", numbers) == "49999.5"
    # Mean 49,999.5; the distances 0.5, 1.5, ... 49,999.5 each appear four times: 4 × 50,000² / 2 / 200,000.
    assert summarize_values("number-mean-absolute-deviation", numbers) == "25000"
    days = [f"2024-01-{day:02d}" for day in range(1, 32)] * 3_000
    assert summarize_values("date-distinct", days) == 31


# Through the CLI: grouping, --having, sorting, --totals and --describe.


def summarize(*arguments):
    result = CliRunner().invoke(main, ["summarize", *arguments])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


# Fictional deposits by account, served as the targets dataset (bucket, label, target). TFSA: 100,
# 200, 300, 400 and a missing amount; RRSP: 1000 and 3000; Cash: a missing amount and the text "n/a".
FLOWS = [
    {"bucket": "TFSA", "target": 100, "label": "first"},
    {"bucket": "RRSP", "target": "1000", "label": None},
    {"bucket": "TFSA", "target": 200.0, "label": "a longer note"},
    {"bucket": "Cash", "target": None, "label": ""},
    {"bucket": "TFSA", "target": "300", "label": None},
    {"bucket": "RRSP", "target": 3000, "label": "transfer in"},
    {"bucket": "TFSA", "target": 400, "label": "the longest note here"},
    {"bucket": "Cash", "target": "n/a", "label": "pending"},
    {"bucket": "TFSA", "target": "", "label": "x"},
]
QUERY = (
    "targets",
    "--group-by",
    "bucket",
    "--metric",
    "p10=number-p10:target",
    "--metric",
    "p90=number-p90:target",
    "--metric",
    "iqr=number-iqr:target",
    "--metric",
    "mad=number-mean-absolute-deviation:target",
    "--metric",
    "filled=present-percent:target",
    "--metric",
    "note=longest-text:label",
)
# TFSA 100, 200, 300, 400: p10 at rank 0.3 is 130, p90 at rank 2.7 is 370, Q1 175 and Q3 325,
# mean 250 with distances 150, 50, 50, 150; four of five amounts are present.
# RRSP 1000, 3000: p10 1200, p90 2800, Q1 1500, Q3 2500, mean 2000 with distances 1000 each.
# Cash has no numbers, and one of its two cells ("n/a") is present.
GROUPS = {
    "TFSA": {
        "bucket": "TFSA",
        "p10": "130",
        "p90": "370",
        "iqr": "150",
        "mad": "100",
        "filled": "80",
        "note": "the longest note here",
    },
    "RRSP": {
        "bucket": "RRSP",
        "p10": "1200",
        "p90": "2800",
        "iqr": "1000",
        "mad": "1000",
        "filled": "100",
        "note": "transfer in",
    },
    "Cash": {"bucket": "Cash", "p10": None, "p90": None, "iqr": None, "mad": None, "filled": "50", "note": "pending"},
}


@pytest.fixture
def flows(monkeypatch):
    rows = [dict(row) for row in FLOWS]
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    return rows


def test_grouped_summaries(flows):
    assert summarize(*QUERY) == [GROUPS["TFSA"], GROUPS["RRSP"], GROUPS["Cash"]]


def test_having_and_sort_read_the_decimal_results_as_numbers(flows):
    # As text "1000" < "150" < "80"; as numbers 80 < 100 and 150 < 1000.
    assert summarize(*QUERY, "--having", "gt:iqr=200") == [GROUPS["RRSP"]]
    assert summarize(*QUERY, "--having", "lt:filled=90") == [GROUPS["TFSA"], GROUPS["Cash"]]
    assert summarize(*QUERY, "--sort", "iqr") == [GROUPS["TFSA"], GROUPS["RRSP"], GROUPS["Cash"]]
    assert summarize(*QUERY, "--sort", "filled", "--descending") == [GROUPS["RRSP"], GROUPS["TFSA"], GROUPS["Cash"]]
    # longest-text returns text, which sorts as text: "pending" < "the longest note here" < "transfer in".
    assert summarize(*QUERY, "--sort", "note") == [GROUPS["Cash"], GROUPS["TFSA"], GROUPS["RRSP"]]


def test_totals_cover_every_row(flows):
    # All six amounts 100, 200, 300, 400, 1000, 3000: p10 at rank 0.5 is 150, p90 at rank 4.5 is 2000,
    # Q1 at 1.25 is 225 and Q3 at 3.75 is 850. The mean is 5000 / 6; the four amounts below it lie
    # 4 × 5000 / 6 - 1000 = 7000 / 3 away in all and the two above it 4000 - 2 × 5000 / 6 = 7000 / 3,
    # so the mean distance is 14000 / 3 / 6 = 7000 / 9. Seven of nine cells (all but null and "") are present.
    totals = summarize(*QUERY, "--totals")[-1]
    assert totals == {
        "bucket": None,
        "p10": "150",
        "p90": "2000",
        "iqr": "625",
        "mad": "777.7777777777777777777777778",
        "filled": "77.77777777777777777777777778",
        "note": "the longest note here",
    }


def test_date_distinct_by_group(monkeypatch):
    rows = [
        {"key": "a", "value": "2024-01-02"},
        {"key": "b", "value": "2024-01-02T10:00:00"},
        {"key": "a", "value": "2024-01-02 15:30"},
        {"key": "a", "value": "2024-01-03"},
        {"key": "b", "value": "not a date"},
    ]
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    query = ("config", "--group-by", "key", "--metric", "days=date-distinct:value")
    assert summarize(*query) == [{"key": "a", "days": 2}, {"key": "b", "days": 1}]
    assert summarize(*query, "--having", "gt:days=1") == [{"key": "a", "days": 2}]


def test_no_rows_give_empty_results(monkeypatch):
    monkeypatch.setattr(reports, "load_source", lambda *args: [])
    metrics = []
    for index, operation in enumerate(FURTHER_OPERATIONS):
        metrics += ["--metric", f"m{index}={operation}:value"]
    assert summarize("config", *metrics) == [
        {"m0": None, "m1": None, "m2": None, "m3": None, "m4": None, "m5": 0, "m6": None}
    ]


def test_describe_lists_the_new_operations_last(monkeypatch):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("describe loaded the source"))
    operations = summarize("accounts", "--describe")["operations"]
    assert len(operations) == 57
    assert operations[-7:] == [
        "number-p10",
        "number-p90",
        "number-iqr",
        "number-mean-absolute-deviation",
        "present-percent",
        "date-distinct",
        "longest-text",
    ]


def test_the_new_operations_need_a_field(monkeypatch):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("an invalid query loaded the source"))
    result = CliRunner().invoke(main, ["summarize", "config", "--metric", "p=number-p10"])
    assert result.exit_code == 2
    assert "Operation 'number-p10' requires a field from: key, value." in result.output
