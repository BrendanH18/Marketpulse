"""Shared report behavior and the complete dataset/operation integration matrix."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports

OPERATIONS = (
    "fields",
    "omit",
    "where",
    "not",
    "contains",
    "prefix",
    "suffix",
    "present",
    "missing",
    "sort",
    "descending",
    "offset",
    "limit",
    "unique",
    "count",
    "jsonl",
    "csv",
    "tsv",
    "markdown",
    "page-info",
)


@pytest.mark.parametrize("source", sorted(reports.SOURCES))
@pytest.mark.parametrize("operation", OPERATIONS)
def test_dataset_operation_matrix(monkeypatch, source, operation):
    """Every source schema supports every shared operation through the real Click entry point."""
    schema = reports.SOURCES[source]
    first, second = schema[:2]
    data = [dict.fromkeys(schema, "Alpha"), dict.fromkeys(schema, "Beta"), dict.fromkeys(schema, None)]
    monkeypatch.setattr(reports, "load_source", lambda *args: data)
    options = {
        "fields": ["--fields", first],
        "omit": ["--omit", second],
        "where": ["--where", first + "=Alpha"],
        "not": ["--not", first + "=Alpha"],
        "contains": ["--contains", first + "=LP"],
        "prefix": ["--prefix", first + "=al"],
        "suffix": ["--suffix", first + "=HA"],
        "present": ["--present", first],
        "missing": ["--missing", first],
        "sort": ["--sort", first],
        "descending": ["--sort", first, "--descending"],
        "offset": ["--offset", "1"],
        "limit": ["--limit", "1"],
        "unique": ["--unique", first],
        "count": ["--count"],
        "jsonl": ["--format", "jsonl"],
        "csv": ["--format", "csv"],
        "tsv": ["--format", "tsv"],
        "markdown": ["--format", "markdown"],
        "page-info": ["--page-info"],
    }
    result = CliRunner().invoke(main, ["report", source, *options[operation]])
    assert result.exit_code == 0, result.output
    if operation == "count":
        assert result.output == "3\n"
    elif operation == "jsonl":
        assert [json.loads(line) for line in result.output.splitlines()] == data
    elif operation in ("csv", "tsv"):
        parsed = list(csv.DictReader(io.StringIO(result.output), delimiter="\t" if operation == "tsv" else ","))
        assert len(parsed) == 3 and parsed[0][first] == "Alpha" and parsed[-1][first] == ""
    elif operation == "markdown":
        assert "| " + first in result.output and "Alpha" in result.output
    else:
        payload = json.loads(result.output)
        if operation == "page-info":
            assert payload["total"] == 3 and payload["source"] == source
            assert payload["rows"] == data
        elif operation == "fields":
            assert payload == [{first: row[first]} for row in data]
        elif operation == "omit":
            assert all(second not in row and first in row for row in payload)
        else:
            expected = {
                "where": data[:1],
                "not": data[1:],
                "contains": data[:1],
                "prefix": data[:1],
                "suffix": data[:1],
                "present": data[:2],
                "missing": data[2:],
                "sort": data,
                "descending": [data[1], data[0], data[2]],
                "offset": data[1:],
                "limit": data[:1],
                "unique": data,
            }
            assert payload == expected[operation]


@pytest.fixture
def rows(monkeypatch):
    data = [
        {"key": "a", "value": 10},
        {"key": "b", "value": None},
        {"key": "a", "value": 2},
        {"key": "c", "value": 10},
    ]
    monkeypatch.setattr(reports, "load_source", lambda *args: data)
    return data


def test_numeric_multikey_and_pipeline(rows):
    result = CliRunner().invoke(
        main,
        [
            "report",
            "config",
            "--unique",
            "key",
            "--sort",
            "value",
            "--sort",
            "key",
            "--descending",
            "--offset",
            "1",
            "--limit",
            "1",
            "--fields",
            "key",
            "--page-info",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "source": "config",
        "total": 3,
        "offset": 1,
        "limit": 1,
        "rows": [{"key": "a"}],
    }
    result = CliRunner().invoke(main, ["report", "config", "--sort", "value"])
    assert [row["value"] for row in json.loads(result.output)] == [2, 10, 10, None]


@pytest.mark.parametrize(
    "options",
    [
        ["--fields", "bogus"],
        ["--where", "key"],
        ["--sort", "bogus"],
        ["--descending"],
        ["--page-info", "--format", "csv"],
        ["--count", "--limit", "1"],
        ["--fields", "key", "--omit", "value"],
        ["--omit", "key,value"],
        ["--fields", "key,key"],
        ["--describe", "--limit", "1"],
        ["--limit", "0"],
    ],
)
def test_invalid_options_before_loading(monkeypatch, options):
    def forbidden(*args):
        pytest.fail("invalid report loaded a source")

    monkeypatch.setattr(reports, "load_source", forbidden)
    result = CliRunner().invoke(main, ["report", "config", *options])
    assert result.exit_code == 2, result.output


def test_atomic_output_no_overwrite_and_schema(monkeypatch, tmp_path, rows):
    target = tmp_path / "report.json"
    result = CliRunner().invoke(main, ["report", "config", "--output", str(target)])
    assert result.exit_code == 0 and result.output == ""
    assert json.loads(target.read_text()) == rows
    result = CliRunner().invoke(main, ["report", "config", "--output", str(target)])
    assert result.exit_code == 2 and json.loads(target.read_text()) == rows
    assert list(tmp_path.iterdir()) == [target]
    monkeypatch.setattr(reports, "load_source", lambda *args: pytest.fail("describe loaded source"))
    result = CliRunner().invoke(main, ["report", "config", "--describe"])
    assert json.loads(result.output)["fields"] == ["key", "value"]


def test_export_escaping_and_nested_values(monkeypatch):
    data = [{"key": "a|b\n<script>", "value": {"x": ["a,b", "é"]}}]
    monkeypatch.setattr(reports, "load_source", lambda *args: data)
    result = CliRunner().invoke(main, ["report", "config", "--format", "markdown"])
    assert "a&#124;b<br>&lt;script&gt;" in result.output
    result = CliRunner().invoke(main, ["report", "config", "--format", "csv"])
    parsed = list(csv.DictReader(io.StringIO(result.output)))
    assert parsed[0]["key"] == data[0]["key"]
    assert json.loads(parsed[0]["value"]) == data[0]["value"]


def test_output_publish_race_preserves_winner(monkeypatch, tmp_path, rows):
    target = tmp_path / "race.json"
    original = reports.os.link

    def race(src, dst):
        target.write_text("winner")
        return original(src, dst)

    monkeypatch.setattr(reports.os, "link", race)
    result = CliRunner().invoke(main, ["report", "config", "--output", str(target)])
    assert result.exit_code == 1 and target.read_text() == "winner"
    assert list(tmp_path.iterdir()) == [target]
