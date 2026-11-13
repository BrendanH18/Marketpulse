"""The capability matrix for #143: each of its 30 new report operations on every source.

Each case runs through the real Click entry point on fixed rows. The expected results are literal
values worked out by hand from the documented behavior of each operation, so the matrix checks
behavior, not registration: nothing here calls the derive, filter, metric or format code to build
an expectation. When a case fails, fix the implementation or the documentation, never the
expected value.
"""

import json
from collections import Counter
from typing import Any, NamedTuple

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports

FILTER, SELECT, METRIC, GROUP, FORMAT = "filter", "select", "metric", "group", "format"


class Case(NamedTuple):
    name: str  # the operation, spelled as documented
    family: str
    values: list[Any]  # one row per value, held in the source's first field; the second field is the row index
    arguments: list[str]  # CLI arguments after the source; {f} is the source's first field
    # By family: the derived value of each row, the indices of the rows kept, the metric result,
    # the summary rows (with {f} as the grouping column) or the text of each first-column cell.
    expected: Any


# A calendar date written in fullwidth digits; date-like values need ASCII digits.
FULLWIDTH_DATE = "\uff12\uff10\uff12\uff14-\uff10\uff13-\uff10\uff15"

CASES = [
    # B. Row filters match the report text of a cell: a string is itself, null is empty and any
    # other value is its canonical JSON (true, 10, [1, 2], {"a": 2}).
    Case(
        "regex",
        FILTER,
        ["Alpha", "alpha", "beta-1", 10, 2.5, True, False, None, "", [1, 2], [2, 3], {"a": 2}, {"A": 2}],
        ["--regex", "{f}=[A-Z]|1"],
        [0, 2, 3, 9, 12],
    ),
    Case(
        "not-regex",
        FILTER,
        ["Alpha", "ALTO", "alpha", "pal", "Beta", "123", 456, "12a", 7.5, None, True, [1]],
        ["--not-regex", r"{f}=(?i)^al|^\d+$"],
        [3, 4, 7, 8, 9, 10, 11],
    ),
    Case(
        "iglob",
        FILTER,
        ["XEQT.TO", True, "to", "Toe", "vfv.to", "XEQT.TO ", False, None, 10],
        ["--iglob", "{f}=[xt]*?[oe]"],
        [0, 1, 3],
    ),
    Case(
        "not-glob",
        FILTER,
        ["Alpha", "alpha", "A", "BA1", 10, 1, 1.5, True, [1, 2], None],
        ["--not-glob", "{f}=[A1]?*"],
        [1, 2, 3, 5, 7, 8, 9],
    ),
    Case(
        "contains-any",
        FILTER,
        ["TSX:XEQT", "nyse arca", "NASDAQ", 100, 1.5, [10], {"x": "Tsx"}, True, None, ""],
        ["--contains-any", '{f}=["tsx","NYSE","10"]'],
        [0, 1, 3, 5, 6],
    ),
    Case(
        "contains-all",
        FILTER,
        ["XEQT.TO", "equity", "EQ", "teq", "tech", ["t", "EQ"], {"eq": True}, {"eq": 1}, None, 0],
        ["--contains-all", '{f}=["eq","T"]'],
        [0, 1, 3, 5, 6],
    ),
    Case(
        "date-from",
        FILTER,
        [
            "2024-03-04",
            "2024-03-05",
            "2024-03-05T00:00:00Z",
            "2024-03-04T23:59:59",
            "2024-12-31 10:00",
            "2025-01-01",
            "2024-04-31",
            "2024-03-05x",
            "9999",
            20240306,
            None,
        ],
        ["--date-from", "{f}=2024-03-05"],
        [1, 2, 4, 5],
    ),
    Case(
        "date-to",
        FILTER,
        [
            "2024-03-06",
            "2024-03-05",
            "2024-03-05T23:59:59Z",
            "2024-03-06 00:00",
            "2023-12-31",
            "2024-02-30",
            "2024-3-5",
            "",
            "0000",
            20240305,
            None,
        ],
        ["--date-to", "{f}=2024-03-05"],
        [1, 2, 4],
    ),
    # Typed equality: 0 equals 0.0 and differs from false and "0", also inside the item.
    Case(
        "has-item",
        FILTER,
        [[[0], 1], [[0.0]], [[False]], [0], [["0"]], [[0, 0]], [[]], "[[0]]", {"0": [0]}, None],
        ["--has-item", "{f}=[0]"],
        [0, 1],
    ),
    Case(
        "has-key",
        FILTER,
        [{"a": 1}, {"a": None}, {"A": 1}, {"ab": 1}, {"b": {"a": 1}}, {}, ["a"], "a", '{"a": 1}', None],
        ["--has-key", "{f}=a"],
        [0, 1],
    ),
    # C. Keyed row selection. Keys are the canonical JSON of the cell: 1, 1.0 and true are three
    # keys, null and "" are two, and an object's key order does not matter.
    Case(
        "duplicates",
        SELECT,
        ["a", "b", "a", "A", 1, 1.0, True, 1, None, None, [1, 2], [1, 2], [2, 1], {"x": 1, "y": 2}, {"y": 2, "x": 1}],
        ["--duplicates", "{f}"],
        [0, 2, 4, 7, 8, 9, 10, 11, 13, 14],
    ),
    Case(
        "singletons",
        SELECT,
        ["x", "X", "x", 0, 0.0, False, "0", None, "", [], [], {"k": [1]}, {"k": [1.0]}],
        ["--singletons", "{f}"],
        [1, 3, 4, 5, 6, 7, 8, 11, 12],
    ),
    Case(
        "unique-last",
        SELECT,
        ["a", "b", "a", 1, 1.0, True, "b", 1, None, "c", None],
        ["--unique-last", "{f}"],
        [2, 4, 5, 6, 7, 9, 10],
    ),
    # D. Summary operations: summarize SOURCE --metric NAME=OPERATION:FIELD.
    Case(
        "date-min",
        METRIC,
        ["2024-03-05", "2023-12-31T23:59:59Z", "2024-01-01 00:00", "2022-02-30", "2021-1-1", "1999", 19990101, None],
        ["--metric", "result=date-min:{f}"],
        "2023-12-31",
    ),
    Case(
        "date-max",
        METRIC,
        ["2024-03-05", "2024-03-06T01:00:00", "2024-03-04 23:00", "2024-04-31", "2024-12-1", "9999", 20250101, None],
        ["--metric", "result=date-max:{f}"],
        "2024-03-06",
    ),
    Case(
        "date-count",
        METRIC,
        [
            "2024-02-29",
            "2024-02-29",
            "2023-02-28T12:00:00Z",
            "2024-02-29 08:00",
            "2023-02-29",
            "2024-2-29",
            "2024-02-29x",
            "",
            20240229,
            True,
            None,
        ],
        ["--metric", "result=date-count:{f}"],
        4,
    ),
    # 2023-12-31 to 2024-03-01 crosses a leap day: 31 + 29 + 1 days.
    Case(
        "date-span",
        METRIC,
        ["2024-03-01", "2024-02-28T18:00:00Z", "2023-12-31 23:59", "2024-02-30", "2025-13-01", 5, None],
        ["--metric", "result=date-span:{f}"],
        61,
    ),
    # 0.1, 0.2, 0.3, 0.4: mean 0.25, squared deviations 0.0225 + 0.0025 + 0.0025 + 0.0225 = 0.05, over 4.
    Case(
        "number-variance",
        METRIC,
        [0.1, "0.2", 0.3, "0.4", True, "NaN", "Infinity", "", "x", [1], None],
        ["--metric", "result=number-variance:{f}"],
        "0.0125",
    ),
    # -4, 1, 1, -4: mean -1.5, every deviation ±2.5, variance 6.25.
    Case(
        "number-stdev",
        METRIC,
        [-4, "1", 1.0, "-4.0", False, "NaN", "-Infinity", "n/a", {}, None],
        ["--metric", "result=number-stdev:{f}"],
        "2.5",
    ),
    # Sorted 3.5, 7, 10, 20.5, 40, 100: position 5 × 0.25 = 1.25, so 7 + 0.25 × (10 - 7).
    Case(
        "number-q1",
        METRIC,
        [40, "10", 20.5, 7, "3.5", 100, True, "NaN", "ten", [7], None],
        ["--metric", "result=number-q1:{f}"],
        "7.75",
    ),
    # Sorted -4, -1.5, 0.5, 2: position 3 × 0.75 = 2.25, so 0.5 + 0.25 × (2 - 0.5).
    Case(
        "number-q3",
        METRIC,
        ["-1.5", "2.00", 0.5, -4, False, "Infinity", "", None],
        ["--metric", "result=number-q3:{f}"],
        "0.875",
    ),
    # Typed values: 1 equals 1.0 and differs from true; false differs from 0.
    Case(
        "value-counts",
        METRIC,
        ["b", "a", "b", 1, 1.0, True, None, "a", "b", None, False, 0, 1],
        ["--metric", "result=value-counts:{f}"],
        [["b", 3], [1, 3], ["a", 2], [None, 2], [True, 1], [False, 1], [0, 1]],
    ),
    Case(
        "repeated-values",
        METRIC,
        ["x", 0, False, "x", [0], [False], 0.0, [0.0], None, "X", {"k": 0}, {"k": False}, 0, [0]],
        ["--metric", "result=repeated-values:{f}"],
        ["x", 0, [0]],
    ),
    # E. Grouped-summary steps. Every row of a group holds the same number here, so the group's
    # quartile is that number, as a decimal string that --having must read as a number: "10" and
    # "12.5" exceed 9, "9" does not, and the other groups have a single row. Pagination comes later.
    Case(
        "having",
        GROUP,
        ["10", "9", "9.5", "12.5", "10", "n/a", "9", "100", "12.5"],
        [
            *("--group-by", "{f}", "--metric", "rows=count", "--metric", "quartile=number-q1:{f}"),
            *("--having", "gt:rows=1", "--having", "gt:quartile=9", "--limit", "2"),
        ],
        [{"{f}": "10", "rows": 2, "quartile": "10"}, {"{f}": "12.5", "rows": 2, "quartile": "12.5"}],
    ),
    # The "zz" row is filtered out; a (2), b (3), c (1) and d (4) remain. --having drops c, the
    # sort puts d first and the page keeps two groups; the closing row still counts all ten rows.
    Case(
        "totals",
        GROUP,
        ["a", "b", "c", "d", "b", "zz", "d", "a", "d", "b", "d"],
        [
            *("--group-by", "{f}", "--metric", "rows=count", "--not-glob", "{f}=z*", "--having", "gt:rows=1"),
            *("--sort", "rows", "--descending", "--limit", "2", "--totals"),
        ],
        [{"{f}": "d", "rows": 4}, {"{f}": "b", "rows": 3}, {"{f}": None, "rows": 10}],
    ),
    # F. Export formats. Expected: the text of each first-column cell; the row index fills the
    # second column and every other column is null.
    Case(
        "html",
        FORMAT,
        ["x & y", '<b class="q">', "it's", "&lt;", "one\ntwo", "a\r\nb", None, 10, 1.5, True, [1, "<"], {"k": "&"}],
        ["--format", "html"],
        [
            "x &amp; y",
            "&lt;b class=&quot;q&quot;&gt;",
            "it&#x27;s",
            "&amp;lt;",
            "one<br>two",
            "a&#13;<br>b",
            "",
            "10",
            "1.5",
            "true",
            "[1, &quot;&lt;&quot;]",
            "{&quot;k&quot;: &quot;&amp;&quot;}",
        ],
    ),
    # Each cell with its alignment: only JSON numbers are right-aligned (">").
    Case(
        "text",
        FORMAT,
        ["Alpha", 5, -12.5, "10", True, None, "two\nlines", "tab\there", "cr\rend", "back\\slash", [1, 2], {"a": 1}],
        ["--format", "text"],
        [
            ("Alpha", "<"),
            ("5", ">"),
            ("-12.5", ">"),
            ("10", "<"),
            ("true", "<"),
            ("", "<"),
            ("two\\nlines", "<"),
            ("tab\\there", "<"),
            ("cr\\rend", "<"),
            ("back\\\\slash", "<"),
            ("[1, 2]", "<"),
            ('{"a": 1}', "<"),
        ],
    ),
    Case(
        "records",
        FORMAT,
        ["Alpha", "", None, 0, 1.5, False, "x: y", "multi\nline", "tab\tsep", "C:\\dir", [1, {"a": None}]],
        ["--format", "records"],
        ["Alpha", "", "", "0", "1.5", "false", "x: y", "multi\\nline", "tab\\tsep", "C:\\\\dir", '[1, {"a": null}]'],
    ),
    Case(
        "lines",
        FORMAT,
        ["Alpha", "", None, 0, -1.5, True, [1, "b"], {"k": None}, "x y", ["caf\u00e9"]],
        ["--format", "lines", "--fields", "{f}"],
        ["Alpha", "", "", "0", "-1.5", "true", '[1, "b"]', '{"k": null}', "x y", '["caf\u00e9"]'],
    ),
    # Expected: the JSON text of the first column's array.
    Case(
        "json-columns",
        FORMAT,
        ["Alpha", "", None, 0, 1.0, -2.5, True, False, [1, "b", None], {"k": [True]}],
        ["--format", "json-columns"],
        '["Alpha", "", null, 0, 1.0, -2.5, true, false, [1, "b", null], {"k": [true]}]',
    ),
]


def _grid(schema: tuple[str, ...], texts: list[str]) -> list[list[str]]:
    """The cell texts of every row in column order: the case's text, the row index, then empty nulls."""
    first, second = schema[:2]
    return [
        [text if name == first else str(index) if name == second else "" for name in schema]
        for index, text in enumerate(texts)
    ]


def _html(schema: tuple[str, ...], cells: list[str]) -> str:
    def line(tag: str, texts) -> str:
        return "<tr>" + "".join(f"<{tag}>{text}</{tag}>" for text in texts) + "</tr>\n"

    body = "".join(line("td", row) for row in _grid(schema, cells))
    return "<table>\n<thead>\n" + line("th", schema) + "</thead>\n<tbody>\n" + body + "</tbody>\n</table>\n"


def _text(schema: tuple[str, ...], cells: list[tuple[str, str]]) -> str:
    grid = _grid(schema, [text for text, _ in cells])
    widths = [max([len(name), *(len(row[column]) for row in grid)]) for column, name in enumerate(schema)]
    lines = [
        "  ".join(name.ljust(width) for name, width in zip(schema, widths, strict=True)),
        "  ".join("-" * width for width in widths),
    ]
    for row, (_, alignment) in zip(grid, cells, strict=True):
        # The row index in the second column is a number too; null cells are empty.
        alignments = [alignment, ">", *("<" for _ in schema[2:])]
        padded = [f"{text:{align}{width}}" for text, align, width in zip(row, alignments, widths, strict=True)]
        lines.append("  ".join(padded))
    return "".join(line.rstrip(" ") + "\n" for line in lines)


def _records(schema: tuple[str, ...], cells: list[str]) -> str:
    blocks = [
        "".join(f"{name}: {text}\n" if text else f"{name}:\n" for name, text in zip(schema, row, strict=True))
        for row in _grid(schema, cells)
    ]
    return "\n".join(blocks)


def _lines(schema: tuple[str, ...], cells: list[str]) -> str:
    return "".join(text + "\n" for text in cells)


def _json_columns(schema: tuple[str, ...], first_column: str) -> str:
    count = len(json.loads(first_column))
    columns = [
        first_column,
        "[" + ", ".join(str(index) for index in range(count)) + "]",
        *("[" + ", ".join(["null"] * count) + "]" for _ in schema[2:]),
    ]
    return "{" + ", ".join(f'"{name}": {column}' for name, column in zip(schema, columns, strict=True)) + "}\n"


# The exact output of each format, laid out from the source's own column names.
EXPORTS = {"html": _html, "text": _text, "records": _records, "lines": _lines, "json-columns": _json_columns}


@pytest.mark.parametrize("source", sorted(reports.SOURCES))
@pytest.mark.parametrize("case", CASES, ids=[case.name for case in CASES])
def test_expansion_capability_matrix(monkeypatch, source, case):
    schema = reports.SOURCES[source]
    first, second = schema[:2]
    rows = [{**dict.fromkeys(schema), first: value, second: index} for index, value in enumerate(case.values)]
    before = json.dumps(rows)
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    command = "summarize" if case.family in (METRIC, GROUP) else "report"
    arguments = [argument.replace("{f}", first) for argument in case.arguments]
    result = CliRunner().invoke(main, [command, source, *arguments])
    assert result.exit_code == 0, result.output
    if case.family == FORMAT:
        assert result.output == EXPORTS[case.name](schema, case.expected)
    else:
        if case.family in (FILTER, SELECT):
            expected = [rows[index] for index in case.expected]
        elif case.family == METRIC:
            expected = [{"result": case.expected}]
        else:
            expected = [{key.replace("{f}", first): value for key, value in row.items()} for row in case.expected]
        payload = json.loads(result.output)
        # Compare JSON text, not Python equality, so true/1 and 1/1.0 mix-ups are caught.
        assert json.dumps(payload, sort_keys=True) == json.dumps(expected, sort_keys=True)
        assert [list(row) for row in payload] == [list(row) for row in expected]
    assert json.dumps(rows) == before  # source rows are never modified


# The 50 datasets that existed before #143 (#136, #142) and the seven it adds.
EARLIER_MODULES = ("report_portfolio", "report_catalog", "report_ledger", "report_system", "report_reference")
NEW_SOURCES = (
    "contribution-room snapshot-classes alert-conditions chart-periods tui-keys workspaces report-operations"
).split()
NEW_OPERATIONS = {
    FILTER: "regex not-regex iglob not-glob contains-any contains-all date-from date-to has-item has-key",
    SELECT: "duplicates singletons unique-last",
    METRIC: (
        "date-min date-max date-count date-span number-variance number-stdev number-q1 number-q3 value-counts "
        "repeated-values"
    ),
    GROUP: "having totals",
    FORMAT: "html text records lines json-columns",
}


def test_inventory_matches_documented_capabilities():
    import importlib

    earlier = [
        name for module in EARLIER_MODULES for name in importlib.import_module(f"marketpulse.cli.{module}").SOURCES
    ]
    assert len(earlier) == 50 and len(reports.SOURCES) == 57
    assert list(reports.SOURCES) == [*earlier, *NEW_SOURCES]

    operations = [(name, family) for family, names in NEW_OPERATIONS.items() for name in names.split()]
    assert [(case.name, case.family) for case in CASES] == operations
    assert len({case.name for case in CASES}) == len(CASES) == 30
    assert Counter(case.family for case in CASES) == {FILTER: 10, SELECT: 3, METRIC: 10, GROUP: 2, FORMAT: 5}
    assert set(EXPORTS) == {case.name for case in CASES if case.family == FORMAT}
    # The 7 new sources × the 150 earlier shared operations (100 report and summary operations and
    # 50 derive functions), plus the 30 new operations × all 57 sources.
    assert len(NEW_SOURCES) * 150 + len(CASES) * len(reports.SOURCES) == 2760

    for source, schema in reports.SOURCES.items():
        # The matrix needs two distinct source fields, and its metric names must differ from the
        # first field, which it groups on.
        assert len(set(schema[:2])) == 2, source
        assert schema[0] not in {"result", "rows", "quartile"}, source
