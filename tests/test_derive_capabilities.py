"""Independent expected results for all 50 × 50 dataset/derive-function combinations."""

import json
import re
from pathlib import Path

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, report_derive, reports

# Function, argument ({other} is the source's second field), first-field values,
# second-field values (None numbers the rows), expected derived values. The
# expectations are worked out by hand from the documented behavior and never
# call the implementation, so the matrix checks behavior, not registration.
CASES = [
    (
        "year",
        None,
        ["2024-02-29", "1999-12-31T23:59:59Z", "2024-02-30", 2024, None],
        None,
        [2024, 1999, None, None, None],
    ),
    ("quarter", None, ["2024-01-15", "2024-04-01", "2024-09-30", "2024-12-31", "x"], None, [1, 2, 3, 4, None]),
    ("month", None, ["2024-02-29", "2023-11-05 08:30", "2024-13-01", None], None, [2, 11, None, None]),
    ("day", None, ["2024-02-29", "2023-11-05", "2023-02-29", ""], None, [29, 5, None, None]),
    ("weekday", None, ["2024-01-01", "2024-01-07", "2023-12-30", "Monday"], None, [1, 7, 6, None]),
    (
        "day-of-year",
        None,
        ["2024-12-31", "2023-12-31", "2024-03-01", "2024-01-01", True],
        None,
        [366, 365, 61, 1, None],
    ),
    ("iso-week", None, ["2024-01-01", "2021-01-03", "2024-12-30", "2024-06-15", []], None, [1, 53, 1, 24, None]),
    ("year-month", None, ["2024-02-29", "0987-06-05", "2024-2-29", None], None, ["2024-02", "0987-06", None, None]),
    (
        "year-quarter",
        None,
        ["2024-05-17", "2023-12-31T00:00:00+05:30", "2023-12-32", 0],
        None,
        ["2024-Q2", "2023-Q4", None, None],
    ),
    (
        "year-week",
        None,
        ["2024-12-30", "2021-01-03", "2024-06-15", "2024-W24"],
        None,
        ["2025-W01", "2020-W53", "2024-W24", None],
    ),
    (
        "month-name",
        None,
        ["2024-01-31", "2024-09-01", "2024-12-25T12:00", "September"],
        None,
        ["January", "September", "December", None],
    ),
    (
        "weekday-name",
        None,
        ["2024-01-01", "2024-01-07", "2023-12-30", None],
        None,
        ["Monday", "Sunday", "Saturday", None],
    ),
    (
        "date",
        None,
        ["2024-02-29T23:59:59.999Z", "2024-02-29 00:00", "2024-02-29", "2024-02-29T24:00", "20240229"],
        None,
        ["2024-02-29", "2024-02-29", "2024-02-29", None, None],
    ),
    (
        "month-start",
        None,
        ["2024-02-29", "2023-07-15T10:00:00-04:00", "nope"],
        None,
        ["2024-02-01", "2023-07-01", None],
    ),
    (
        "month-end",
        None,
        ["2024-02-10", "2023-02-10", "2024-04-30", "2024-12-01", 5],
        None,
        ["2024-02-29", "2023-02-28", "2024-04-30", "2024-12-31", None],
    ),
    (
        "quarter-start",
        None,
        ["2024-02-29", "2024-06-30", "2024-08-15", "2024-12-31", None],
        None,
        ["2024-01-01", "2024-04-01", "2024-07-01", "2024-10-01", None],
    ),
    (
        "quarter-end",
        None,
        ["2024-02-29", "2024-04-01", "2024-08-15", "2024-10-01", ""],
        None,
        ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31", None],
    ),
    ("year-start", None, ["2024-02-29", "1999-12-31", {}], None, ["2024-01-01", "1999-01-01", None]),
    ("year-end", None, ["2024-02-29", "1999-01-01", False], None, ["2024-12-31", "1999-12-31", None]),
    (
        "week-start",
        None,
        ["2024-01-01", "2024-01-07", "2025-01-01", "0001-01-01", "x"],
        None,
        ["2024-01-01", "2024-01-01", "2024-12-30", "0001-01-01", None],
    ),
    (
        "is-weekend",
        None,
        ["2023-12-30", "2023-12-31", "2024-01-01", "2024-01-05", None],
        None,
        [True, True, False, False, None],
    ),
    (
        "days-from",
        "2024-01-01",
        ["2024-01-01", "2024-03-01", "2023-12-31", "2025-01-01T08:00", "soon"],
        None,
        [0, 60, -1, 366, None],
    ),
    ("number", None, ["12.50", 3, -0.0, "1e3", True, "abc", None], None, [12.5, 3, 0, 1000, None, None, None]),
    ("abs", None, [-2.5, "3", 0, "-0.10", False], None, [2.5, 3, 0, 0.1, None]),
    ("negate", None, [2.5, "-3", 0, "x"], None, [-2.5, 3, 0, None]),
    ("sign", None, [-2.5, "3", 0, "-0", None, True], None, [-1, 1, 0, 0, None, None]),
    ("floor", None, [2.5, -2.5, "7", "-0.1", [2.5]], None, [2, -3, 7, -1, None]),
    ("ceil", None, [2.5, -2.5, "7", "0.1", {}], None, [3, -2, 7, 1, None]),
    ("round", "2", [1.125, 1.135, "2.675", -1.125, 5, "1e-3", False], None, [1.12, 1.14, 2.68, -1.12, 5, 0, None]),
    ("bin", "100", [250, 99.99, -50, "300", 0, None], None, [200, 0, -100, 300, 0, None]),
    ("add", "0.1", [0.2, "1", -0.1, None], None, [0.3, 1.1, 0, None]),
    ("multiply", "1.5", [2, "0.5", -4, "x"], None, [3, 0.75, -6, None]),
    ("add-field", "{other}", [1, "2.5", 3, None, True], [10, 0.5, "x", 4, 1], [11, 3, None, None, None]),
    ("subtract-field", "{other}", [10, "2.5", 3, None], [4, 0.5, None, 1], [6, 2, None, None]),
    ("multiply-field", "{other}", [3, "0.1", -2, "x"], [4, 3, "2.5", 1], [12, 0.3, -5, None]),
    (
        "divide-field",
        "{other}",
        [10, 1, "7.5", 5, None],
        [4, 3, "2.5", 0, 2],
        [2.5, 0.3333333333333333, 3, None, None],
    ),
    ("lower", None, ["AbC", "ÉCOLE", "", 5, None], None, ["abc", "école", "", None, None]),
    ("upper", None, ["AbC", "straße", "", False], None, ["ABC", "STRASSE", "", None]),
    ("trim", None, ["  a b  ", "\tx\n", "", None, 1], None, ["a b", "x", "", None, None]),
    ("left", "3", ["XEQT.TO", "ab", "", "日本語テキスト", 12345], None, ["XEQ", "ab", "", "日本語", None]),
    ("before", ".", ["XEQT.TO", "RCI.B.TO", "AAPL", ".TO", None, 1.5], None, ["XEQT", "RCI", "AAPL", "", None, None]),
    ("after-last", ".", ["XEQT.TO", "RCI.B.TO", "AAPL", "TO.", None, 1.5], None, ["TO", "TO", "", "", None, None]),
    ("length", None, ["abc", "", [1, 2], {}, {"a": 1}, 5, None, True], None, [3, 0, 2, 0, 1, None, None, None]),
    (
        "text",
        None,
        [None, "x", 5, 1.5, True, [1, "a"], {"b": 1, "a": None}],
        None,
        ["", "x", "5", "1.5", "true", '[1, "a"]', '{"a": null, "b": 1}'],
    ),
    (
        "type",
        None,
        ["x", 1, 1.5, True, None, [], {}],
        None,
        ["string", "number", "number", "boolean", "null", "array", "object"],
    ),
    ("is-missing", None, [None, "", " ", 0, False, [], {}], None, [True, True, False, False, False, False, False]),
    ("coalesce", '{"none": true}', [None, "", 0, False, [None]], None, [{"none": True}, "", 0, False, [None]]),
    ("equals", "1", [1, 1.0, True, "1", [1], None], None, [True, True, False, False, False, False]),
    ("item", "-1", [[1, 2, 3], ["a"], [], "abc", {"0": 1}, None], None, [3, "a", None, None, None, None]),
    (
        "key",
        "symbol",
        [{"symbol": "FIC.TO", "n": 1}, {"symbol": None}, {"n": 1}, ["symbol"], "symbol", None],
        None,
        ["FIC.TO", None, None, None, None, None],
    ),
]


def _rows(schema, values, others):
    first, second = schema[:2]
    return [
        {**dict.fromkeys(schema), first: value, second: i if others is None else others[i]}
        for i, value in enumerate(values)
    ]


def _specification(schema, function, argument):
    specification = f"derived_value={function}:{schema[0]}"
    return specification if argument is None else f"{specification}:{argument.replace('{other}', schema[1])}"


@pytest.mark.parametrize("source", sorted(reports.SOURCES))
@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_derive_function_dataset_matrix(monkeypatch, source, case):
    function, argument, values, others, expected = case
    schema = reports.SOURCES[source]
    data = _rows(schema, values, others)
    before = json.dumps(data)
    monkeypatch.setattr(reports, "load_source", lambda *args: data)
    result = CliRunner().invoke(main, ["report", source, "--derive", _specification(schema, function, argument)])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    # The derived column follows the unchanged source columns.
    assert [list(row) for row in rows] == [[*schema, "derived_value"]] * len(data)
    # Compare JSON text rather than Python equality to protect boolean/number and int/float types.
    assert json.dumps(rows) == json.dumps(
        [{**row, "derived_value": value} for row, value in zip(data, expected, strict=True)]
    )
    assert json.dumps(data) == before


@pytest.mark.parametrize("case", CASES, ids=[case[0] for case in CASES])
def test_every_function_feeds_summaries(monkeypatch, case):
    function, argument, values, others, expected = case
    schema = reports.SOURCES["transactions"]
    data = _rows(schema, values, others)
    monkeypatch.setattr(reports, "load_source", lambda *args: data)
    arguments = ["--derive", _specification(schema, function, argument), "--metric", "result=values:derived_value"]
    result = CliRunner().invoke(main, ["summarize", "transactions", *arguments])
    assert result.exit_code == 0, result.output
    assert json.dumps(json.loads(result.output)) == json.dumps([{"result": expected}])


def test_inventory_matches_documented_five_thousand():
    from marketpulse.cli import report_ledger, report_reference, report_system
    from marketpulse.cli.report_metrics import OPERATIONS

    new_sources = {**report_ledger.SOURCES, **report_system.SOURCES, **report_reference.SOURCES}
    functions = [function.name for function in report_derive.FUNCTIONS]
    assert len(new_sources) == 25
    assert len(reports.SOURCES) == 50
    # 20 base and 40 added report operations plus 40 summary operations reach every new dataset.
    assert len(new_sources) * (20 + 40 + len(OPERATIONS)) == 2500
    assert [case[0] for case in CASES] == functions
    assert len(set(functions)) == 50
    assert len(functions) * len(reports.SOURCES) == 2500
    assert all("derived_value" not in schema and len(schema) >= 2 for schema in reports.SOURCES.values())


def test_documented_inventory_matches_the_code():
    from marketpulse.cli import report_ledger, report_reference, report_system

    guide = (Path(__file__).parent.parent / "docs" / "cli-report-derived-datasets.md").read_text(encoding="utf-8")
    new_modules = (report_ledger, report_system, report_reference)
    new_sources = [(name, schema, module) for module in new_modules for name, schema in module.SOURCES.items()]
    datasets = re.findall(r"^\| (\d+) \| `([a-z-]+)` \| ([a-z_, ]+) \| (.+) \|$", guide, re.MULTILINE)
    # The guide marks option names as code; the descriptions are otherwise the ones `report sources` prints.
    assert [(number, name, fields, description.replace("`", "")) for number, name, fields, description in datasets] == [
        (str(number), name, ", ".join(schema), module.DESCRIPTIONS[name])
        for number, (name, schema, module) in enumerate(new_sources, 1)
    ]
    functions = re.findall(r"^\| (\d+) \| `([a-z-]+)` \| (—|`[A-Z]+`) \| .+ \|$", guide, re.MULTILINE)
    assert functions == [
        (str(number), function.name, "—" if function.argument is None else f"`{function.argument}`")
        for number, function in enumerate(report_derive.FUNCTIONS, 1)
    ]

    def bounds(text):
        low, high = text.replace(",", "").split("–")
        return int(low), int(high)

    blocks = [(bounds(span), name) for span, name in re.findall(r"\| ([\d,]+–[\d,]+) \| `([a-z-]+)` ", guide)]
    existing = sorted(block for block in blocks if block[0][1] <= 2500)
    derived = sorted(block for block in blocks if block[0][0] > 2500)
    assert existing == [((100 * i + 1, 100 * i + 100), name) for i, (name, _, _) in enumerate(new_sources)]
    assert derived == [((2500 + 50 * i + 1, 2500 + 50 * i + 50), name) for i, name in enumerate(reports.SOURCES)]
