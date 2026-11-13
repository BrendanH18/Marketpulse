"""The five export formats of #143: html, text, records, lines and json-columns.

Every expected output is written out by hand from the specification; no test calls a serializer to build
an expectation. Click's ``Result.output`` and ``Result.stdout`` fold CRLF into LF, so exact CLI output is
read from ``stdout_bytes``.
"""

import json
import os
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports
from marketpulse.cli.base import App
from marketpulse.cli.report_formats import serialize, validate
from marketpulse.models import Account, Transaction, TxnType

NEW_FORMATS = ("html", "text", "records", "lines", "json-columns")
OLDER_FORMATS = ("json", "jsonl", "csv", "tsv", "markdown")
ONE_COLUMN = "--format lines requires exactly one output column."
LINE_BREAK = "Cannot write a value containing a line break with --format lines."
NO_OVERWRITE = "--output must name a new file; refusing to overwrite."


def lines_of(*lines):
    """The given lines, each ending in a newline."""
    return "".join(line + "\n" for line in lines)


def html_table(names, rows):
    """An HTML fragment laid out as the specification shows, from already escaped names and cells."""

    def line(tag, cells):
        return "<tr>" + "".join(f"<{tag}>{cell}</{tag}>" for cell in cells) + "</tr>\n"

    body = "".join(line("td", row) for row in rows)
    return "<table>\n<thead>\n" + line("th", names) + "</thead>\n<tbody>\n" + body + "</tbody>\n</table>\n"


def run(monkeypatch, rows, *arguments):
    """Run the CLI on fixed rows; the source name only selects a schema (config has key and value)."""
    monkeypatch.setattr(reports, "load_source", lambda *args: rows)
    return CliRunner().invoke(main, list(arguments))


def forbid_loading(monkeypatch):
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("an invalid query loaded its source"))


def printed(result):
    """Standard output exactly as written, after a successful run."""
    assert result.exit_code == 0, result.output
    return result.stdout_bytes.decode("utf-8")


# ---------------------------------------------------------------------------------------------
# Exact output at unit level: an ordinary table, no rows, a single column and a single row.

FIELDS = ["symbol", "quantity", "note"]
TABLE = [
    {"symbol": "FIC.TO", "quantity": 12, "note": "Fictional fund"},
    {"symbol": "DEMO.V", "quantity": 2.5, "note": None},
]

EXACT = [
    pytest.param(
        "html",
        FIELDS,
        TABLE,
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>symbol</th><th>quantity</th><th>note</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>FIC.TO</td><td>12</td><td>Fictional fund</td></tr>",
            "<tr><td>DEMO.V</td><td>2.5</td><td></td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-table",
    ),
    pytest.param(
        "html",
        FIELDS,
        [],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>symbol</th><th>quantity</th><th>note</th></tr>",
            "</thead>",
            "<tbody>",
            "</tbody>",
            "</table>",
        ),
        id="html-empty",
    ),
    pytest.param(
        "html",
        ["quantity"],
        TABLE,
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>quantity</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>12</td></tr>",
            "<tr><td>2.5</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-column",
    ),
    pytest.param(
        "html",
        FIELDS,
        TABLE[:1],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>symbol</th><th>quantity</th><th>note</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>FIC.TO</td><td>12</td><td>Fictional fund</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-row",
    ),
    # Widths: symbol 6 (name and cells), quantity 8 (its name), note 14 ("Fictional fund").
    pytest.param(
        "text",
        FIELDS,
        TABLE,
        lines_of(
            "symbol  quantity  note",
            "------  --------  --------------",
            "FIC.TO        12  Fictional fund",
            "DEMO.V       2.5",
        ),
        id="text-table",
    ),
    pytest.param(
        "text",
        FIELDS,
        [],
        lines_of("symbol  quantity  note", "------  --------  ----"),
        id="text-empty",
    ),
    pytest.param(
        "text",
        ["quantity"],
        TABLE,
        lines_of("quantity", "--------", "      12", "     2.5"),
        id="text-column",
    ),
    pytest.param(
        "text",
        FIELDS,
        TABLE[:1],
        lines_of(
            "symbol  quantity  note",
            "------  --------  --------------",
            "FIC.TO        12  Fictional fund",
        ),
        id="text-row",
    ),
    pytest.param(
        "records",
        FIELDS,
        TABLE,
        lines_of(
            "symbol: FIC.TO",
            "quantity: 12",
            "note: Fictional fund",
            "",
            "symbol: DEMO.V",
            "quantity: 2.5",
            "note:",
        ),
        id="records-table",
    ),
    pytest.param("records", FIELDS, [], "", id="records-empty"),
    pytest.param("records", ["quantity"], TABLE, lines_of("quantity: 12", "", "quantity: 2.5"), id="records-column"),
    pytest.param(
        "records",
        FIELDS,
        TABLE[:1],
        lines_of("symbol: FIC.TO", "quantity: 12", "note: Fictional fund"),
        id="records-row",
    ),
    # lines always has one column; a null cell is an empty line.
    pytest.param("lines", ["note"], TABLE, lines_of("Fictional fund", ""), id="lines-table"),
    pytest.param("lines", ["symbol"], [], "", id="lines-empty"),
    pytest.param("lines", ["quantity"], TABLE, lines_of("12", "2.5"), id="lines-column"),
    pytest.param("lines", ["symbol"], TABLE[:1], lines_of("FIC.TO"), id="lines-row"),
    pytest.param(
        "json-columns",
        FIELDS,
        TABLE,
        '{"symbol": ["FIC.TO", "DEMO.V"], "quantity": [12, 2.5], "note": ["Fictional fund", null]}\n',
        id="json-columns-table",
    ),
    pytest.param(
        "json-columns",
        FIELDS,
        [],
        '{"symbol": [], "quantity": [], "note": []}\n',
        id="json-columns-empty",
    ),
    pytest.param("json-columns", ["quantity"], TABLE, '{"quantity": [12, 2.5]}\n', id="json-columns-column"),
    pytest.param(
        "json-columns",
        FIELDS,
        TABLE[:1],
        '{"symbol": ["FIC.TO"], "quantity": [12], "note": ["Fictional fund"]}\n',
        id="json-columns-row",
    ),
]


@pytest.mark.parametrize(("output_format", "fields", "rows", "expected"), EXACT)
def test_exact_output_of_each_format(output_format, fields, rows, expected):
    before = json.dumps(rows)
    assert serialize(rows, fields, output_format) == expected
    assert json.dumps(rows) == before


# ---------------------------------------------------------------------------------------------
# Cell conventions: null is empty, strings are themselves, everything else is canonical JSON.

# value, report text, HTML cell, whether it is a JSON number (right-aligned by text), JSON text.
CELLS = [
    (None, "", "", False, "null"),
    (True, "true", "true", False, "true"),
    (False, "false", "false", False, "false"),
    (0, "0", "0", True, "0"),
    (-7, "-7", "-7", True, "-7"),
    (1.0, "1.0", "1.0", True, "1.0"),
    (-0.0, "-0.0", "-0.0", True, "-0.0"),
    (1e-07, "1e-07", "1e-07", True, "1e-07"),
    (2.5e20, "2.5e+20", "2.5e+20", True, "2.5e+20"),
    ("", "", "", False, '""'),
    ("10", "10", "10", False, '"10"'),
    ("Café", "Café", "Café", False, '"Café"'),
    ("日本語", "日本語", "日本語", False, '"日本語"'),
    ("🙂🇨🇦", "🙂🇨🇦", "🙂🇨🇦", False, '"🙂🇨🇦"'),
    ([1, [2, "x"], None], '[1, [2, "x"], null]', "[1, [2, &quot;x&quot;], null]", False, '[1, [2, "x"], null]'),
    (
        {"b": 1, "a": [True, {"d": None, "c": "é"}]},
        '{"a": [true, {"c": "é", "d": null}], "b": 1}',
        "{&quot;a&quot;: [true, {&quot;c&quot;: &quot;é&quot;, &quot;d&quot;: null}], &quot;b&quot;: 1}",
        False,
        # Unspecified: json-columns keeps native values, and like the json format keeps object key order.
        '{"b": 1, "a": [true, {"d": null, "c": "é"}]}',
    ),
    ([], "[]", "[]", False, "[]"),
    ({}, "{}", "{}", False, "{}"),
]
CELL_IDS = [
    "null",
    "true",
    "false",
    "zero",
    "negative-int",
    "whole-float",
    "negative-zero",
    "small-float",
    "large-float",
    "empty-string",
    "numeric-string",
    "accent",
    "cjk",
    "emoji",
    "nested-array",
    "nested-object",
    "empty-array",
    "empty-object",
]


@pytest.mark.parametrize(("value", "text", "html_cell", "number", "json_text"), CELLS, ids=CELL_IDS)
def test_cell_conventions_in_each_format(value, text, html_cell, number, json_text):
    rows, fields = [{"value_column": value}], ["value_column"]
    assert serialize(rows, fields, "html") == html_table(["value_column"], [[html_cell]])
    # The 12-character name makes a right-aligned number show its padding; left-aligned text loses its
    # padding with the trailing spaces.
    width = max(12, len(text))
    assert serialize(rows, fields, "text") == lines_of(
        "value_column", "-" * width, text.rjust(width) if number else text
    )
    assert serialize(rows, fields, "records") == (f"value_column: {text}\n" if text else "value_column:\n")
    assert serialize(rows, fields, "lines") == text + "\n"
    assert serialize(rows, fields, "json-columns") == '{"value_column": [' + json_text + "]}\n"


@pytest.mark.parametrize("output_format", NEW_FORMATS)
def test_cell_conventions_through_the_cli(monkeypatch, output_format):
    rows = [{"key": cell[0], "value": None} for cell in CELLS]
    texts = [cell[1] for cell in CELLS]
    width = max(3, *(len(text) for text in texts))
    expected = {
        "html": html_table(["key"], [[cell[2]] for cell in CELLS]),
        "text": lines_of("key", "-" * width, *(cell[1].rjust(width) if cell[3] else cell[1] for cell in CELLS)),
        "records": "\n".join(f"key: {text}\n" if text else "key:\n" for text in texts),
        "lines": lines_of(*texts),
        "json-columns": '{"key": [' + ", ".join(cell[4] for cell in CELLS) + "]}\n",
    }
    before = json.dumps(rows)
    result = run(monkeypatch, rows, "report", "config", "--fields", "key", "--format", output_format)
    assert printed(result) == expected[output_format]
    assert json.dumps(rows) == before


# ---------------------------------------------------------------------------------------------
# html


def test_html_escapes_text_then_converts_line_breaks():
    values = [
        "x & y",
        '<b class="q">',
        "it's",
        "&amp;",
        "&#13;",
        "<br>",
        "one\ntwo",
        "cr\ronly",
        "a\r\nb",
        "\n",
        ["x\ny", "<"],
        {"k": "&"},
    ]
    cells = [
        "x &amp; y",
        "&lt;b class=&quot;q&quot;&gt;",
        "it&#x27;s",
        "&amp;amp;",
        "&amp;#13;",
        "&lt;br&gt;",
        "one<br>two",
        "cr&#13;only",
        "a&#13;<br>b",
        "<br>",
        # The report text of an array is JSON, which already writes the line feed as backslash-n.
        r"[&quot;x\ny&quot;, &quot;&lt;&quot;]",
        "{&quot;k&quot;: &quot;&amp;&quot;}",
    ]
    rows = [{"cell": value} for value in values]
    assert serialize(rows, ["cell"], "html") == html_table(["cell"], [[cell] for cell in cells])


def test_html_escapes_header_cells_the_same_way():
    fields = ["a&b", "<c>", "\"d\" 'e'", "two\nlines", "cr\rx"]
    assert serialize([], fields, "html") == lines_of(
        "<table>",
        "<thead>",
        "<tr><th>a&amp;b</th><th>&lt;c&gt;</th><th>&quot;d&quot; &#x27;e&#x27;</th>"
        "<th>two<br>lines</th><th>cr&#13;x</th></tr>",
        "</thead>",
        "<tbody>",
        "</tbody>",
        "</table>",
    )


def test_html_writes_tabs_and_other_control_characters_unchanged():
    # Unspecified: only &, <, >, the two quotes, CR and LF are rewritten.
    assert serialize([{"cell": "a\tb\x0cc\x00"}], ["cell"], "html") == html_table(["cell"], [["a\tb\x0cc\x00"]])


# ---------------------------------------------------------------------------------------------
# text


def test_text_aligns_each_cell_by_its_own_type():
    # Only JSON numbers are right-aligned: not booleans, numeric strings or null.
    rows = [{"mixed": 5}, {"mixed": "5"}, {"mixed": True}, {"mixed": -12.5}, {"mixed": None}, {"mixed": "wide text"}]
    assert serialize(rows, ["mixed"], "text") == lines_of(
        "mixed", "---------", "        5", "5", "true", "    -12.5", "", "wide text"
    )


# Shared by text and records: each cell's one-line text, then the escaped width of each.
ESCAPE_ROWS = [
    {"name": "back\\slash", "n": 1},
    {"name": "two\nlines", "n": 2},
    {"name": "cr\rend", "n": 3},
    {"name": "tab\there", "n": 4},
    {"name": "a\\nb", "n": 5},  # a backslash then n, which must stay apart from a line feed
    {"name": "\r\n", "n": 6},
    {"name": ["x\ny"], "n": 7},  # JSON already escapes the line feed; its backslash is then doubled
]


def test_text_escapes_cells_onto_one_line_and_counts_the_escaped_width():
    # The widest cell is back\\slash, 11 characters once escaped (10 before).
    assert serialize(ESCAPE_ROWS, ["name", "n"], "text") == lines_of(
        "name         n",
        "-----------  -",
        r"back\\slash  1",
        r"two\nlines   2",
        r"cr\rend      3",
        r"tab\there    4",
        r"a\\nb        5",
        r"\r\n         6",
        r'["x\\ny"]    7',
    )


def test_text_removes_trailing_spaces_from_every_line():
    rows = [
        {"label": "Fictional", "amount": 5, "note": None},
        {"label": "x", "amount": -12.5, "note": "padded  "},
        {"label": "", "amount": None, "note": ""},
    ]
    text = serialize(rows, ["label", "amount", "note"], "text")
    assert text == lines_of(
        "label      amount  note",
        "---------  ------  --------",
        "Fictional       5",
        "x           -12.5  padded",
        "",
    )
    assert not any(line.endswith(" ") for line in text.split("\n"))


def test_text_keeps_trailing_characters_that_are_not_spaces():
    # The padding is spaces. A no-break space, an ideographic space or a unit separator that ends a value
    # is part of its report text, and the specification removes only trailing spaces.
    rows = [{"name": "Fictional "}, {"name": "日本　"}, {"name": "unit\x1f"}]
    assert serialize(rows, ["name"], "text") == lines_of("name", "----------", "Fictional ", "日本　", "unit\x1f")


def test_text_widths_count_code_points():
    # The specification counts widths in characters; the implementation counts code points (len). CJK
    # characters and emoji, two terminal columns wide, count one each, and a flag (two code points) two.
    rows = [{"name": "日本", "n": 1}, {"name": "🙂", "n": 22}, {"name": "🇨🇦", "n": 3}]
    assert serialize(rows, ["name", "n"], "text") == lines_of(
        "name  n", "----  --", "日本     1", "🙂     22", "🇨🇦     3"
    )


# ---------------------------------------------------------------------------------------------
# records


def test_records_blocks_values_and_separators():
    rows = [
        {"name": "Fictional", "note": "", "extra": None},
        {"name": "  ", "note": "kept  ", "extra": "x: y"},
        {"name": "日本", "note": "no-break ", "extra": [1, None]},
    ]
    assert serialize(rows, ["name", "note", "extra"], "records") == lines_of(
        "name: Fictional",
        "note:",
        "extra:",
        "",
        "name:   ",
        "note: kept  ",
        "extra: x: y",
        "",
        "name: 日本",
        "note: no-break ",
        "extra: [1, null]",
    )


def test_records_use_the_same_one_line_escapes_as_text():
    assert serialize(ESCAPE_ROWS, ["name", "n"], "records") == lines_of(
        r"name: back\\slash",
        "n: 1",
        "",
        r"name: two\nlines",
        "n: 2",
        "",
        r"name: cr\rend",
        "n: 3",
        "",
        r"name: tab\there",
        "n: 4",
        "",
        r"name: a\\nb",
        "n: 5",
        "",
        r"name: \r\n",
        "n: 6",
        "",
        r'name: ["x\\ny"]',
        "n: 7",
    )


# ---------------------------------------------------------------------------------------------
# lines


def test_lines_writes_each_report_text_without_a_header():
    values = ["Fictional", "", None, 0, -1.5, True, [1, "b"], {"k": None}, ["a\nb"], "trailing  ", "日本🙂", "a\tb"]
    assert serialize([{"cell": value} for value in values], ["cell"], "lines") == lines_of(
        "Fictional", "", "", "0", "-1.5", "true", '[1, "b"]', '{"k": null}', r'["a\nb"]', "trailing  ", "日本🙂", "a\tb"
    )


@pytest.mark.parametrize("value", ["two\nlines", "carriage\rreturn", "\r\n", "\n", "ends\n"])
def test_lines_rejects_a_line_feed_or_carriage_return(value):
    with pytest.raises(click.ClickException) as error:
        serialize([{"cell": "fine"}, {"cell": value}], ["cell"], "lines")
    assert error.value.message == LINE_BREAK
    assert error.value.exit_code == 1


def test_lines_writes_other_line_separators_unchanged():
    # Unspecified: only a line feed or a carriage return counts as a line break; vertical tab, form feed,
    # NEL and the Unicode line and paragraph separators are written as they are.
    values = ["a\x0bb", "a\x0cb", "a\x85b", "a b", "a b"]
    assert serialize([{"cell": value} for value in values], ["cell"], "lines") == lines_of(*values)


# ---------------------------------------------------------------------------------------------
# json-columns


def test_json_columns_keep_native_types_and_the_selected_column_order():
    rows = [
        {"value": True, "label": "1"},
        {"value": 1, "label": "true"},
        {"value": 1.0, "label": None},
        {"value": -0.0, "label": ""},
        {"value": 1e-07, "label": "Café 日本 🙂"},
        {"value": None, "label": [1, {"b": 2, "a": 1}]},
        {"value": "", "label": {"z": [], "a": None}},
        {"value": "a\nb\x1b", "label": 2.5e20},
    ]
    # JSON text keeps true apart from 1 and 1 apart from 1.0. Unspecified: like the json format, non-ASCII
    # is written as is and nested objects keep their key order.
    assert serialize(rows, ["value", "label"], "json-columns") == (
        '{"value": [true, 1, 1.0, -0.0, 1e-07, null, "", "a\\nb\\u001b"], '
        '"label": ["1", "true", null, "", "Café 日本 🙂", [1, {"b": 2, "a": 1}], {"z": [], "a": null}, 2.5e+20]}\n'
    )
    reordered = serialize(rows, ["label", "value"], "json-columns")
    assert reordered.startswith('{"label": ["1", "true", null')
    assert list(json.loads(reordered)) == ["label", "value"]


# ---------------------------------------------------------------------------------------------
# validate


@pytest.mark.parametrize("columns", [["key"], ["value"]])
def test_validate_accepts_lines_with_one_column(columns):
    assert validate("lines", columns) is None


@pytest.mark.parametrize("columns", [[], ["key", "value"], ["a", "b", "c"]])
def test_validate_rejects_lines_without_exactly_one_column(columns):
    with pytest.raises(click.UsageError) as error:
        validate("lines", columns)
    assert error.value.message == ONE_COLUMN
    assert error.value.exit_code == 2


@pytest.mark.parametrize("count", [0, 1, 2, 7])
@pytest.mark.parametrize("output_format", [*OLDER_FORMATS, "html", "text", "records", "json-columns"])
def test_validate_accepts_every_other_format_with_any_number_of_columns(output_format, count):
    assert validate(output_format, [f"column_{index}" for index in range(count)]) is None


def test_both_commands_offer_exactly_the_ten_formats_with_json_by_default():
    expected = ["json", "jsonl", "csv", "tsv", "markdown", "html", "text", "records", "lines", "json-columns"]
    assert list(reports.FORMATS) == expected
    for command in ("report", "summarize"):
        (option,) = [param for param in main.commands[command].params if param.name == "output_format"]
        assert list(option.type.choices) == expected
        assert option.default == "json"


@pytest.mark.parametrize(
    "arguments", [["report", "config"], ["summarize", "config", "--metric", "rows=count"]], ids=["report", "summarize"]
)
def test_unknown_format_is_a_usage_error_listing_the_choices(monkeypatch, arguments):
    forbid_loading(monkeypatch)
    result = CliRunner().invoke(main, [*arguments, "--format", "xml"])
    assert result.exit_code == 2
    assert "'markdown', 'html', 'text', 'records', 'lines', 'json-columns'" in result.output


# ---------------------------------------------------------------------------------------------
# report: each format through the CLI

REPORT_ROWS = [
    {"key": "fund", "value": 12},
    {"key": "note", "value": "Café & <b>"},
    {"key": "flag", "value": None},
]
NONE_MATCH = ["--where", "key=missing"]

REPORT_CASES = [
    pytest.param(
        "html",
        [],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>key</th><th>value</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>fund</td><td>12</td></tr>",
            "<tr><td>note</td><td>Café &amp; &lt;b&gt;</td></tr>",
            "<tr><td>flag</td><td></td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-table",
    ),
    pytest.param(
        "html",
        NONE_MATCH,
        lines_of(
            "<table>", "<thead>", "<tr><th>key</th><th>value</th></tr>", "</thead>", "<tbody>", "</tbody>", "</table>"
        ),
        id="html-empty",
    ),
    pytest.param(
        "html",
        ["--fields", "value"],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>value</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>12</td></tr>",
            "<tr><td>Café &amp; &lt;b&gt;</td></tr>",
            "<tr><td></td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-column",
    ),
    pytest.param(
        "html",
        ["--limit", "1"],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>key</th><th>value</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>fund</td><td>12</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-row",
    ),
    pytest.param(
        "text",
        [],
        lines_of("key   value", "----  ----------", "fund          12", "note  Café & <b>", "flag"),
        id="text-table",
    ),
    pytest.param("text", NONE_MATCH, lines_of("key  value", "---  -----"), id="text-empty"),
    pytest.param(
        "text",
        ["--fields", "value"],
        lines_of("value", "----------", "        12", "Café & <b>", ""),
        id="text-column",
    ),
    pytest.param("text", ["--limit", "1"], lines_of("key   value", "----  -----", "fund     12"), id="text-row"),
    pytest.param(
        "records",
        [],
        lines_of("key: fund", "value: 12", "", "key: note", "value: Café & <b>", "", "key: flag", "value:"),
        id="records-table",
    ),
    pytest.param("records", NONE_MATCH, "", id="records-empty"),
    pytest.param(
        "records",
        ["--fields", "value"],
        lines_of("value: 12", "", "value: Café & <b>", "", "value:"),
        id="records-column",
    ),
    pytest.param("records", ["--limit", "1"], lines_of("key: fund", "value: 12"), id="records-row"),
    pytest.param("lines", ["--omit", "value"], lines_of("fund", "note", "flag"), id="lines-table"),
    pytest.param("lines", [*NONE_MATCH, "--fields", "key"], "", id="lines-empty"),
    pytest.param("lines", ["--fields", "value"], lines_of("12", "Café & <b>", ""), id="lines-column"),
    pytest.param("lines", ["--limit", "1", "--fields", "key"], lines_of("fund"), id="lines-row"),
    pytest.param(
        "json-columns",
        [],
        '{"key": ["fund", "note", "flag"], "value": [12, "Café & <b>", null]}\n',
        id="json-columns-table",
    ),
    pytest.param("json-columns", NONE_MATCH, '{"key": [], "value": []}\n', id="json-columns-empty"),
    pytest.param(
        "json-columns",
        ["--fields", "value"],
        '{"value": [12, "Café & <b>", null]}\n',
        id="json-columns-column",
    ),
    pytest.param("json-columns", ["--limit", "1"], '{"key": ["fund"], "value": [12]}\n', id="json-columns-row"),
]


@pytest.mark.parametrize(("output_format", "arguments", "expected"), REPORT_CASES)
def test_report_prints_each_format_exactly(monkeypatch, output_format, arguments, expected):
    before = json.dumps(REPORT_ROWS)
    result = run(monkeypatch, REPORT_ROWS, "report", "config", *arguments, "--format", output_format)
    assert printed(result) == expected
    assert json.dumps(REPORT_ROWS) == before


# Source columns (key renamed to name), then the derived kind, the constant tag and the row number n.
DECORATED_ROWS = [{"key": "fund", "value": 12}, {"key": "note", "value": "x"}]
DECORATED = ["--derive", "kind=type:value", "--rename", "key=name", "--constant", 'tag="fictional"']
DECORATED += ["--row-number", "n"]

DECORATED_CASES = [
    pytest.param(
        "html",
        [],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>name</th><th>value</th><th>kind</th><th>tag</th><th>n</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>fund</td><td>12</td><td>number</td><td>fictional</td><td>1</td></tr>",
            "<tr><td>note</td><td>x</td><td>string</td><td>fictional</td><td>2</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-all",
    ),
    pytest.param(
        "html",
        ["--fields", "n,kind,name"],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>n</th><th>kind</th><th>name</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>1</td><td>number</td><td>fund</td></tr>",
            "<tr><td>2</td><td>string</td><td>note</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-fields",
    ),
    pytest.param(
        "html",
        ["--omit", "name,value,tag"],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>kind</th><th>n</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>number</td><td>1</td></tr>",
            "<tr><td>string</td><td>2</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-omit",
    ),
    pytest.param(
        "text",
        [],
        lines_of(
            "name  value  kind    tag        n",
            "----  -----  ------  ---------  -",
            "fund     12  number  fictional  1",
            "note  x      string  fictional  2",
        ),
        id="text-all",
    ),
    pytest.param(
        "text",
        ["--fields", "n,kind,name"],
        lines_of("n  kind    name", "-  ------  ----", "1  number  fund", "2  string  note"),
        id="text-fields",
    ),
    pytest.param(
        "text",
        ["--omit", "name,value,tag"],
        lines_of("kind    n", "------  -", "number  1", "string  2"),
        id="text-omit",
    ),
    pytest.param(
        "records",
        [],
        lines_of(
            "name: fund",
            "value: 12",
            "kind: number",
            "tag: fictional",
            "n: 1",
            "",
            "name: note",
            "value: x",
            "kind: string",
            "tag: fictional",
            "n: 2",
        ),
        id="records-all",
    ),
    pytest.param(
        "records",
        ["--fields", "n,kind,name"],
        lines_of("n: 1", "kind: number", "name: fund", "", "n: 2", "kind: string", "name: note"),
        id="records-fields",
    ),
    pytest.param(
        "records",
        ["--omit", "name,value,tag"],
        lines_of("kind: number", "n: 1", "", "kind: string", "n: 2"),
        id="records-omit",
    ),
    pytest.param(
        "json-columns",
        [],
        '{"name": ["fund", "note"], "value": [12, "x"], "kind": ["number", "string"], '
        '"tag": ["fictional", "fictional"], "n": [1, 2]}\n',
        id="json-columns-all",
    ),
    pytest.param(
        "json-columns",
        ["--fields", "n,kind,name"],
        '{"n": [1, 2], "kind": ["number", "string"], "name": ["fund", "note"]}\n',
        id="json-columns-fields",
    ),
    pytest.param(
        "json-columns",
        ["--omit", "name,value,tag"],
        '{"kind": ["number", "string"], "n": [1, 2]}\n',
        id="json-columns-omit",
    ),
    pytest.param("lines", ["--fields", "name"], lines_of("fund", "note"), id="lines-renamed"),
    pytest.param("lines", ["--fields", "value"], lines_of("12", "x"), id="lines-source"),
    pytest.param("lines", ["--fields", "kind"], lines_of("number", "string"), id="lines-derived"),
    pytest.param("lines", ["--fields", "tag"], lines_of("fictional", "fictional"), id="lines-constant"),
    pytest.param("lines", ["--fields", "n"], lines_of("1", "2"), id="lines-row-number"),
    pytest.param("lines", ["--omit", "name,value,kind,tag"], lines_of("1", "2"), id="lines-omit"),
]


@pytest.mark.parametrize(("output_format", "projection", "expected"), DECORATED_CASES)
def test_report_columns_from_every_output_option_appear_in_each_format(
    monkeypatch, output_format, projection, expected
):
    result = run(monkeypatch, DECORATED_ROWS, "report", "config", *DECORATED, *projection, "--format", output_format)
    assert printed(result) == expected


# ---------------------------------------------------------------------------------------------
# summarize: each format through the CLI, with and without --totals

SUMMARY_ROWS = [
    {"key": "fund", "value": 10},
    {"key": "note", "value": "x & y"},
    {"key": "fund", "value": 2.5},
]
GROUPED = ["--group-by", "key", "--metric", "rows=count", "--metric", "first=first:value"]
# No source row matches, but the closing row still appears: null group, a count of zero.
EMPTY_TOTALS = [*NONE_MATCH, "--group-by", "key", "--metric", "rows=count", "--totals"]

SUMMARY_CASES = [
    pytest.param(
        "html",
        GROUPED,
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>key</th><th>rows</th><th>first</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>fund</td><td>2</td><td>10</td></tr>",
            "<tr><td>note</td><td>1</td><td>x &amp; y</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-table",
    ),
    pytest.param(
        "html",
        [*GROUPED, *NONE_MATCH],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>key</th><th>rows</th><th>first</th></tr>",
            "</thead>",
            "<tbody>",
            "</tbody>",
            "</table>",
        ),
        id="html-empty",
    ),
    pytest.param(
        "html",
        ["--metric", "rows=count"],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>rows</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>3</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-column",
    ),
    pytest.param(
        "html",
        [*GROUPED, "--limit", "1"],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>key</th><th>rows</th><th>first</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>fund</td><td>2</td><td>10</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-row",
    ),
    pytest.param(
        "html",
        [*GROUPED, "--totals"],
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>key</th><th>rows</th><th>first</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>fund</td><td>2</td><td>10</td></tr>",
            "<tr><td>note</td><td>1</td><td>x &amp; y</td></tr>",
            "<tr><td></td><td>3</td><td>10</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-totals",
    ),
    pytest.param(
        "html",
        EMPTY_TOTALS,
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>key</th><th>rows</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td></td><td>0</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html-empty-totals",
    ),
    pytest.param(
        "text",
        GROUPED,
        lines_of("key   rows  first", "----  ----  -----", "fund     2     10", "note     1  x & y"),
        id="text-table",
    ),
    pytest.param("text", [*GROUPED, *NONE_MATCH], lines_of("key  rows  first", "---  ----  -----"), id="text-empty"),
    pytest.param("text", ["--metric", "rows=count"], lines_of("rows", "----", "   3"), id="text-column"),
    pytest.param(
        "text",
        [*GROUPED, "--limit", "1"],
        lines_of("key   rows  first", "----  ----  -----", "fund     2     10"),
        id="text-row",
    ),
    pytest.param(
        "text",
        [*GROUPED, "--totals"],
        lines_of(
            "key   rows  first",
            "----  ----  -----",
            "fund     2     10",
            "note     1  x & y",
            "         3     10",
        ),
        id="text-totals",
    ),
    pytest.param("text", EMPTY_TOTALS, lines_of("key  rows", "---  ----", "        0"), id="text-empty-totals"),
    pytest.param(
        "records",
        GROUPED,
        lines_of("key: fund", "rows: 2", "first: 10", "", "key: note", "rows: 1", "first: x & y"),
        id="records-table",
    ),
    pytest.param("records", [*GROUPED, *NONE_MATCH], "", id="records-empty"),
    pytest.param("records", ["--metric", "rows=count"], lines_of("rows: 3"), id="records-column"),
    pytest.param(
        "records", [*GROUPED, "--limit", "1"], lines_of("key: fund", "rows: 2", "first: 10"), id="records-row"
    ),
    pytest.param(
        "records",
        [*GROUPED, "--totals"],
        lines_of(
            "key: fund",
            "rows: 2",
            "first: 10",
            "",
            "key: note",
            "rows: 1",
            "first: x & y",
            "",
            "key:",
            "rows: 3",
            "first: 10",
        ),
        id="records-totals",
    ),
    pytest.param("records", EMPTY_TOTALS, lines_of("key:", "rows: 0"), id="records-empty-totals"),
    # lines needs one output column: a single metric and no grouping, so there is one summary row
    # unless --having removes it. --totals needs --group-by, so it cannot combine with lines.
    pytest.param("lines", ["--metric", "keys=distinct-values:key"], lines_of('["fund", "note"]'), id="lines-table"),
    pytest.param("lines", ["--metric", "rows=count", "--having", "gt:rows=3"], "", id="lines-empty"),
    pytest.param("lines", ["--metric", "rows=count"], lines_of("3"), id="lines-column"),
    pytest.param("lines", ["--metric", "total=number-sum:value"], lines_of("12.5"), id="lines-row"),
    pytest.param(
        "json-columns",
        GROUPED,
        '{"key": ["fund", "note"], "rows": [2, 1], "first": [10, "x & y"]}\n',
        id="json-columns-table",
    ),
    pytest.param(
        "json-columns",
        [*GROUPED, *NONE_MATCH],
        '{"key": [], "rows": [], "first": []}\n',
        id="json-columns-empty",
    ),
    pytest.param("json-columns", ["--metric", "rows=count"], '{"rows": [3]}\n', id="json-columns-column"),
    pytest.param(
        "json-columns",
        [*GROUPED, "--limit", "1"],
        '{"key": ["fund"], "rows": [2], "first": [10]}\n',
        id="json-columns-row",
    ),
    pytest.param(
        "json-columns",
        [*GROUPED, "--totals"],
        '{"key": ["fund", "note", null], "rows": [2, 1, 3], "first": [10, "x & y", 10]}\n',
        id="json-columns-totals",
    ),
    pytest.param("json-columns", EMPTY_TOTALS, '{"key": [null], "rows": [0]}\n', id="json-columns-empty-totals"),
]


@pytest.mark.parametrize(("output_format", "arguments", "expected"), SUMMARY_CASES)
def test_summarize_prints_each_format_exactly(monkeypatch, output_format, arguments, expected):
    before = json.dumps(SUMMARY_ROWS)
    result = run(monkeypatch, SUMMARY_ROWS, "summarize", "config", *arguments, "--format", output_format)
    assert printed(result) == expected
    assert json.dumps(SUMMARY_ROWS) == before


def test_summarize_text_left_aligns_decimal_string_metrics(monkeypatch):
    # number-sum returns decimal strings ("0" when no value is numeric), which are not JSON numbers.
    arguments = ["--group-by", "key", "--metric", "total=number-sum:value", "--metric", "rows=count"]
    result = run(monkeypatch, SUMMARY_ROWS, "summarize", "config", *arguments, "--format", "text")
    assert printed(result) == lines_of(
        "key   total  rows", "----  -----  ----", "fund  12.5      2", "note  0         1"
    )


# ---------------------------------------------------------------------------------------------
# Validation before loading, and the options the new formats cannot combine with


@pytest.mark.parametrize(
    "arguments",
    [
        ["report", "config"],
        ["report", "config", "--fields", "key,value"],
        ["report", "config", "--omit", "value", "--constant", "tag=1"],
        ["report", "config", "--omit", "key", "--row-number", "n"],
        ["report", "config", "--omit", "key", "--derive", "kind=type:value"],
        ["report", "config", "--rename", "key=name", "--fields", "name,value"],
        ["summarize", "config", "--group-by", "key", "--metric", "rows=count"],
        ["summarize", "config", "--metric", "rows=count", "--metric", "keys=values:key"],
        ["summarize", "config", "--group-by", "key", "--metric", "rows=count", "--totals"],
        ["summarize", "config", "--derive", "kind=type:value", "--group-by", "kind", "--metric", "rows=count"],
    ],
)
def test_lines_requires_exactly_one_output_column_before_loading(monkeypatch, arguments):
    forbid_loading(monkeypatch)
    result = CliRunner().invoke(main, [*arguments, "--format", "lines"])
    assert result.exit_code == 2
    assert ONE_COLUMN in result.output


@pytest.mark.parametrize("value", ["two\nlines", "carriage\rreturn"], ids=["line-feed", "carriage-return"])
def test_lines_with_a_line_break_fails_and_writes_nothing(monkeypatch, tmp_path, value):
    rows = [{"key": "fine", "value": None}, {"key": value, "value": None}]
    folder = tmp_path / "exports"
    folder.mkdir()
    attempts = [
        ["report", "config", "--fields", "key"],
        ["report", "config", "--fields", "key", "--output", str(folder / "keys.txt")],
        ["summarize", "config", "--metric", "last_key=last:key"],
        ["summarize", "config", "--metric", "last_key=last:key", "--output", str(folder / "last.txt")],
    ]
    for arguments in attempts:
        result = run(monkeypatch, rows, *arguments, "--format", "lines")
        assert result.exit_code == 1, result.output
        assert isinstance(result.exception, SystemExit)  # a clean error, not a traceback
        assert result.stdout_bytes == b""
        assert LINE_BREAK in result.stderr
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize("output_format", [*NEW_FORMATS, "jsonl", "csv", "tsv", "markdown"])
def test_page_info_and_count_still_require_json(monkeypatch, output_format):
    forbid_loading(monkeypatch)
    # Every source has at least two fields, so lines needs --fields, which --count also rejects.
    projection = ["--fields", "key"] if output_format == "lines" else []
    runner = CliRunner()
    result = runner.invoke(main, ["report", "config", *projection, "--format", output_format, "--page-info"])
    assert result.exit_code == 2
    assert "--page-info requires JSON row output." in result.output
    result = runner.invoke(main, ["report", "config", *projection, "--format", output_format, "--count"])
    assert result.exit_code == 2
    assert "--count cannot combine with pagination, projection or alternate formats." in result.output
    result = runner.invoke(
        main, ["summarize", "config", "--metric", "rows=count", "--format", output_format, "--page-info"]
    )
    assert result.exit_code == 2
    assert "--page-info requires JSON output." in result.output


@pytest.mark.parametrize("output_format", NEW_FORMATS)
@pytest.mark.parametrize("command", ["report", "summarize"])
def test_describe_rejects_the_new_formats(monkeypatch, command, output_format):
    forbid_loading(monkeypatch)
    result = CliRunner().invoke(main, [command, "config", "--describe", "--format", output_format])
    assert result.exit_code == 2, result.output


# ---------------------------------------------------------------------------------------------
# --output

OUTPUT_ROWS = [{"key": "Café 日本", "value": 1.5}, {"key": "x & y", "value": None}]
WRITTEN = {
    "html": lines_of(
        "<table>",
        "<thead>",
        "<tr><th>key</th></tr>",
        "</thead>",
        "<tbody>",
        "<tr><td>Café 日本</td></tr>",
        "<tr><td>x &amp; y</td></tr>",
        "</tbody>",
        "</table>",
    ),
    "text": lines_of("key", "-------", "Café 日本", "x & y"),
    "records": lines_of("key: Café 日本", "", "key: x & y"),
    "lines": lines_of("Café 日本", "x & y"),
    "json-columns": '{"key": ["Café 日本", "x & y"]}\n',
}


@pytest.mark.parametrize("output_format", NEW_FORMATS)
def test_output_writes_a_new_utf8_file_exactly_as_printed_and_never_overwrites(monkeypatch, tmp_path, output_format):
    folder = tmp_path / "exports"
    folder.mkdir()
    target = folder / "report.out"
    arguments = ["report", "config", "--fields", "key", "--format", output_format]
    shown = run(monkeypatch, OUTPUT_ROWS, *arguments)
    assert printed(shown) == WRITTEN[output_format]
    written = run(monkeypatch, OUTPUT_ROWS, *arguments, "--output", str(target))
    assert written.exit_code == 0, written.output
    assert written.stdout_bytes == b""
    assert target.read_bytes() == shown.stdout_bytes == WRITTEN[output_format].encode("utf-8")

    forbid_loading(monkeypatch)
    again = CliRunner().invoke(main, [*arguments, "--output", str(target)])
    assert again.exit_code == 2
    assert NO_OVERWRITE in again.output
    assert target.read_bytes() == WRITTEN[output_format].encode("utf-8")
    assert list(folder.iterdir()) == [target]


@pytest.mark.parametrize("output_format", ["records", "lines"])
def test_output_of_an_empty_result_is_a_new_empty_file(monkeypatch, tmp_path, output_format):
    target = tmp_path / "empty.out"
    arguments = ["report", "config", *NONE_MATCH, "--fields", "key", "--format", output_format]
    result = run(monkeypatch, OUTPUT_ROWS, *arguments, "--output", str(target))
    assert result.exit_code == 0, result.output
    assert target.read_bytes() == b""


def test_summarize_output_writes_the_totals_table_and_never_overwrites(monkeypatch, tmp_path):
    target = tmp_path / "summary.txt"
    arguments = ["summarize", "config", *GROUPED, "--totals", "--format", "text", "--output", str(target)]
    result = run(monkeypatch, SUMMARY_ROWS, *arguments)
    assert result.exit_code == 0, result.output
    assert result.stdout_bytes == b""
    expected = lines_of(
        "key   rows  first", "----  ----  -----", "fund     2     10", "note     1  x & y", "         3     10"
    )
    assert target.read_bytes() == expected.encode("utf-8")
    forbid_loading(monkeypatch)
    again = CliRunner().invoke(main, arguments)
    assert again.exit_code == 2
    assert NO_OVERWRITE in again.output
    assert target.read_bytes() == expected.encode("utf-8")


# ---------------------------------------------------------------------------------------------
# Fictional saved data, through the real source: no network, no writes, archived accounts hidden.


@pytest.fixture
def saved_note(tracker, monkeypatch):
    store = tracker.store
    active = store.add_account(Account("Fictional Margin", track_cash=True))
    archived = store.add_account(Account("Archived Fictional", track_cash=True, archived=True))
    for account in (active, archived):
        note = "Café & <b>\tfirst\nline"
        store.add_transaction(Transaction(account.saved_id, TxnType.BUY, "2024-01-02", "FIC.TO", 2, 10, note=note))
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    return store


SAVED_FIELDS = ["--fields", "date,account,symbol,note"]
SAVED_CASES = [
    pytest.param(
        "html",
        SAVED_FIELDS,
        lines_of(
            "<table>",
            "<thead>",
            "<tr><th>date</th><th>account</th><th>symbol</th><th>note</th></tr>",
            "</thead>",
            "<tbody>",
            "<tr><td>2024-01-02</td><td>Fictional Margin</td><td>FIC.TO</td>"
            "<td>Café &amp; &lt;b&gt;\tfirst<br>line</td></tr>",
            "</tbody>",
            "</table>",
        ),
        id="html",
    ),
    pytest.param(
        "text",
        SAVED_FIELDS,
        lines_of(
            "date        account           symbol  note",
            "----------  ----------------  ------  -----------------------",
            r"2024-01-02  Fictional Margin  FIC.TO  Café & <b>\tfirst\nline",
        ),
        id="text",
    ),
    pytest.param(
        "records",
        SAVED_FIELDS,
        lines_of("date: 2024-01-02", "account: Fictional Margin", "symbol: FIC.TO", r"note: Café & <b>\tfirst\nline"),
        id="records",
    ),
    pytest.param("lines", ["--fields", "account"], lines_of("Fictional Margin"), id="lines"),
    pytest.param(
        "json-columns",
        SAVED_FIELDS,
        '{"date": ["2024-01-02"], "account": ["Fictional Margin"], "symbol": ["FIC.TO"], '
        '"note": ["Café & <b>\\tfirst\\nline"]}\n',
        id="json-columns",
    ),
]


@pytest.mark.parametrize(("output_format", "projection", "expected"), SAVED_CASES)
def test_formats_on_fictional_saved_transactions(saved_note, fake, output_format, projection, expected):
    changes = saved_note._conn.total_changes
    result = CliRunner().invoke(main, ["report", "transactions", *projection, "--format", output_format])
    assert printed(result) == expected
    assert fake.calls == []
    assert saved_note._conn.total_changes == changes


def test_lines_refuses_a_saved_note_with_a_line_break(saved_note, fake):
    result = CliRunner().invoke(main, ["report", "transactions", "--fields", "note", "--format", "lines"])
    assert result.exit_code == 1
    assert result.stdout_bytes == b""
    assert LINE_BREAK in result.stderr
    assert fake.calls == []


# ---------------------------------------------------------------------------------------------
# Escape characters, non-finite numbers and text UTF-8 cannot encode.

ESCAPED = "\x1b[1mFictional\x1b[0m"


def test_json_columns_print_escape_characters_as_json_escapes(monkeypatch):
    result = run(monkeypatch, [{"key": ESCAPED, "value": None}], "report", "config", "--format", "json-columns")
    assert printed(result) == '{"key": ["\\u001b[1mFictional\\u001b[0m"], "value": [null]}\n'


@pytest.mark.parametrize(
    ("output_format", "expected"),
    [
        ("html", html_table(["key"], [[ESCAPED]])),
        ("text", lines_of("key", "-" * 17, ESCAPED)),
        ("records", lines_of(f"key: {ESCAPED}")),
        ("lines", lines_of(ESCAPED)),
    ],
    ids=["html", "text", "records", "lines"],
)
def test_printed_output_keeps_escape_characters_in_values(monkeypatch, output_format, expected):
    # The report text of a string is the string itself and none of these formats rewrites ESC, so the
    # printed text must hold it. CliRunner's standard output is not a terminal, like a pipe or a redirect.
    result = run(
        monkeypatch, [{"key": ESCAPED, "value": None}], "report", "config", "--fields", "key", "--format", output_format
    )
    assert printed(result) == expected


@pytest.mark.xfail(
    strict=True,
    reason="#145: a nan float from a hand-edited config.toml reaches json.dumps(allow_nan=False): ValueError",
)
@pytest.mark.parametrize("output_format", NEW_FORMATS)
def test_non_finite_config_value_does_not_crash(output_format):
    # nan is valid TOML and the float setting accepts it. Output or a clean CLI error are both acceptable;
    # inside CliRunner a clean error surfaces as SystemExit, a traceback as the original exception.
    Path(os.environ["MARKETPULSE_CONFIG"]).write_text("capital_gains_inclusion = nan\n", encoding="utf-8")
    arguments = ["report", "config", "--where", "key=capital_gains_inclusion", "--fields", "value"]
    result = CliRunner().invoke(main, [*arguments, "--format", output_format])
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(result.exception)


@pytest.mark.parametrize("output_format", NEW_FORMATS)
def test_output_of_a_value_utf8_cannot_encode_fails_cleanly(monkeypatch, tmp_path, output_format):
    # A data path that is not valid UTF-8 reaches Python as a lone surrogate (surrogateescape).
    monkeypatch.setenv("MARKETPULSE_DATA", str(tmp_path / "fic\udcfftional"))
    folder = tmp_path / "exports"
    folder.mkdir()
    target = folder / "paths.out"
    arguments = ["report", "paths", "--where", "name=data", "--fields", "path", "--format", output_format]
    result = CliRunner().invoke(main, [*arguments, "--output", str(target)])
    assert result.exception is None or isinstance(result.exception, SystemExit), repr(result.exception)
    assert result.exit_code == 1 and "Cannot write report" in result.output
    assert list(folder.iterdir()) == []
