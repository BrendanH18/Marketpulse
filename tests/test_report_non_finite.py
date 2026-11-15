"""A NaN or infinity in report data: text shows it, JSON refuses it, and nothing ends in a traceback (#145).

Expected output is written out by hand. Exact text is read from ``stdout_bytes``, because Click's
``Result.output`` folds CRLF into LF.
"""

import math
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports
from marketpulse.cli.base import App
from marketpulse.db import Snapshot

ROWS = [
    {"key": "nan", "value": math.nan},
    {"key": "up", "value": math.inf},
    {"key": "down", "value": -math.inf},
    {"key": "ok", "value": 1.5},
    {"key": "low", "value": -2},
]
REFUSED = (
    "Error: Field 'value' holds NaN or infinity, which JSON cannot represent. "
    "Choose a text format such as --format csv, or leave the field out.\n"
)
JSON_FORMATS = ("json", "jsonl", "json-columns")


@pytest.fixture
def rows(monkeypatch):
    """Every command reads these rows; the source name only selects the schema (config has key and value)."""
    monkeypatch.setattr(reports, "load_source", lambda *args: [dict(row) for row in ROWS])


def run(*arguments):
    return CliRunner().invoke(main, list(arguments))


def printed(*arguments):
    """Standard output exactly as written, after a successful run."""
    result = run(*arguments)
    assert result.exit_code == 0, result.output
    text = result.stdout_bytes.decode("utf-8")
    return text.replace(os.linesep, "\n") if os.linesep != "\n" else text


def refused(*arguments):
    """The message of a run that failed cleanly: exit code 1 from Click, not an unhandled exception."""
    result = run(*arguments)
    assert isinstance(result.exception, SystemExit), repr(result.exception)
    assert result.exit_code == 1
    return result.output


@pytest.mark.parametrize(
    ("output_format", "expected"),
    [
        ("csv", "value\r\nNaN\r\nInfinity\r\n-Infinity\r\n1.5\r\n-2\r\n"),
        ("tsv", "value\r\nNaN\r\nInfinity\r\n-Infinity\r\n1.5\r\n-2\r\n"),
        ("markdown", "| value |\n| --- |\n| NaN |\n| Infinity |\n| -Infinity |\n| 1.5 |\n| -2 |\n"),
        ("lines", "NaN\nInfinity\n-Infinity\n1.5\n-2\n"),
        ("records", "value: NaN\n\nvalue: Infinity\n\nvalue: -Infinity\n\nvalue: 1.5\n\nvalue: -2\n"),
        ("text", "value\n---------\n      NaN\n Infinity\n-Infinity\n      1.5\n       -2\n"),
        (
            "html",
            "<table>\n<thead>\n<tr><th>value</th></tr>\n</thead>\n<tbody>\n"
            "<tr><td>NaN</td></tr>\n<tr><td>Infinity</td></tr>\n<tr><td>-Infinity</td></tr>\n"
            "<tr><td>1.5</td></tr>\n<tr><td>-2</td></tr>\n</tbody>\n</table>\n",
        ),
    ],
)
def test_text_formats_print_non_finite_numbers(rows, output_format, expected):
    assert printed("report", "config", "--fields", "value", "--format", output_format) == expected


@pytest.mark.parametrize("output_format", JSON_FORMATS)
def test_json_formats_refuse_non_finite_numbers_and_name_the_field(rows, tmp_path, output_format):
    target = tmp_path / "report.out"
    assert refused("report", "config", "--format", output_format) == REFUSED
    assert refused("report", "config", "--format", output_format, "--output", str(target)) == REFUSED
    assert not target.exists()


@pytest.mark.parametrize("output_format", JSON_FORMATS)
def test_json_formats_still_write_rows_and_fields_that_are_finite(rows, output_format):
    kept = {
        "json": '[{"key": "ok", "value": 1.5}, {"key": "low", "value": -2}]\n',
        "jsonl": '{"key": "ok", "value": 1.5}\n{"key": "low", "value": -2}\n',
        "json-columns": '{"key": ["ok", "low"], "value": [1.5, -2]}\n',
    }
    without_field = {
        "json": '[{"key": "nan"}, {"key": "up"}, {"key": "down"}, {"key": "ok"}, {"key": "low"}]\n',
        "jsonl": '{"key": "nan"}\n{"key": "up"}\n{"key": "down"}\n{"key": "ok"}\n{"key": "low"}\n',
        "json-columns": '{"key": ["nan", "up", "down", "ok", "low"]}\n',
    }
    assert printed("report", "config", "--format", output_format, "--in", 'key=["ok", "low"]') == kept[output_format]
    assert printed("report", "config", "--format", output_format, "--omit", "value") == without_field[output_format]


@pytest.mark.parametrize("value", [[1, math.nan], {"depth": {"limit": math.inf}}])
def test_a_non_finite_number_inside_an_array_or_object_counts(monkeypatch, value):
    monkeypatch.setattr(reports, "load_source", lambda *args: [{"key": "nested", "value": value}])
    assert refused("report", "config") == REFUSED
    expected = "[1, NaN]\n" if isinstance(value, list) else '{"depth": {"limit": Infinity}}\n'
    assert printed("report", "config", "--fields", "value", "--format", "lines") == expected


def test_stringify_gives_the_report_text_and_encode_json_refuses(rows):
    assert printed("report", "config", "--stringify", "value", "--where", "key=nan") == (
        '[{"key": "nan", "value": "NaN"}]\n'
    )
    assert refused("report", "config", "--encode-json", "value", "--format", "csv") == REFUSED
    assert printed("report", "config", "--encode-json", "value", "--gt", "value=0", "--format", "csv") == (
        "key,value\r\nok,1.5\r\n"
    )


def test_text_filters_match_the_report_text_and_number_filters_skip_it(rows):
    def keys(*arguments):
        return printed("report", "config", *arguments, "--fields", "key", "--format", "lines").split()

    assert keys("--where", "value=NaN") == ["nan"]
    assert keys("--contains", "value=infinity") == ["up", "down"]
    assert keys("--regex", "value=^-") == ["down", "low"]
    # A number filter compares finite numbers only, so infinity is neither above nor below a bound.
    assert keys("--gt", "value=0") == ["ok"]
    assert keys("--lt", "value=0") == ["low"]


def test_report_sorts_finite_numbers_first_and_non_finite_ones_as_text(rows):
    def order(*arguments):
        return printed("report", "config", *arguments, "--fields", "value", "--format", "lines").split()

    assert order("--sort", "value") == ["-2", "1.5", "-Infinity", "Infinity", "NaN"]
    assert order("--sort", "value", "--descending") == ["1.5", "-2", "NaN", "Infinity", "-Infinity"]
    assert order("--sort-ci", "value") == ["-2", "1.5", "-Infinity", "Infinity", "NaN"]


def test_summarize_groups_sorts_and_measures_around_non_finite_numbers(rows):
    grouped = ("summarize", "config", "--metric", "rows=count", "--group-by", "value")
    assert printed(*grouped, "--sort", "value", "--format", "csv") == (
        "value,rows\r\n-2,1\r\n1.5,1\r\n-Infinity,1\r\nInfinity,1\r\nNaN,1\r\n"
    )
    assert printed(*grouped, "--sort", "value", "--descending", "--format", "csv") == (
        "value,rows\r\n1.5,1\r\n-2,1\r\nNaN,1\r\nInfinity,1\r\n-Infinity,1\r\n"
    )
    assert refused(*grouped) == REFUSED
    # Numeric metrics read finite numbers only: 1.5 and -2.
    metrics = (
        "--metric",
        "total=number-sum:value",
        "--metric",
        "n=number-count:value",
        "--metric",
        "top=number-max:value",
    )
    assert printed("summarize", "config", *metrics) == '[{"total": "-0.5", "n": 2, "top": "1.5"}]\n'
    # A metric that returns the cell itself carries the non-finite number into the output.
    assert refused("summarize", "config", "--metric", "first=first:value") == (REFUSED.replace("'value'", "'first'"))
    assert printed("summarize", "config", "--metric", "first=first:value", "--format", "lines") == "NaN\n"


def test_a_nan_setting_in_config_toml_reports_cleanly():
    Path(os.environ["MARKETPULSE_CONFIG"]).write_text("capital_gains_inclusion = nan\n", encoding="utf-8")
    setting = ("report", "config", "--where", "key=capital_gains_inclusion", "--fields", "value")
    assert printed(*setting, "--format", "lines") == "NaN\n"
    assert refused(*setting) == REFUSED
    assert printed("report", "config", "--where", "key=base_currency") == '[{"key": "base_currency", "value": "CAD"}]\n'


def test_a_nan_in_a_saved_snapshot_breakdown_reports_cleanly(tracker, monkeypatch):
    # sqlite's JSON text can hold NaN: the store writes and reads it with Python's permissive json module.
    tracker.store.upsert_snapshot(
        Snapshot("2024-03-05", 1200, 1000, 1300, "CAD", {"classes": {"cash": 610.25, "equity": math.nan}})
    )
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    assert printed("report", "snapshot-classes", "--format", "csv") == (
        "date,asset_class,value,currency\r\n2024-03-05,cash,610.25,CAD\r\n2024-03-05,equity,NaN,CAD\r\n"
    )
    assert refused("report", "snapshot-classes") == REFUSED
    assert printed("summarize", "snapshot-classes", "--metric", "total=number-sum:value") == '[{"total": "610.25"}]\n'
