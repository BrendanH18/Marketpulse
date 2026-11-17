"""The field catalog supports offline schema discovery across every report source."""

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from marketpulse.cli import main, reports
from marketpulse.cli.base import App


@pytest.fixture
def cli(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Schema discovery must not open the tracker or market client")

    monkeypatch.setattr("marketpulse.services.Tracker.open", forbidden)
    monkeypatch.setattr("marketpulse.market.MarketData.__init__", forbidden)
    runner = CliRunner()

    def invoke(*args):
        result = runner.invoke(main, args, catch_exceptions=False)
        assert result.exit_code == 0, result.output
        assert not Path(os.environ["MARKETPULSE_DATA"]).exists()
        return json.loads(result.output)

    return invoke


def test_report_fields_covers_registry_and_preserves_schema_order(cli):
    rows = cli("report", "report-fields")
    expected = [
        {"source": source, "group": module.GROUP, "position": position, "field": field}
        for module in reports.SOURCE_MODULES
        for source, schema in module.SOURCES.items()
        for position, field in enumerate(schema, 1)
    ]
    assert rows == expected
    assert all(tuple(row) == reports.SOURCES["report-fields"] for row in rows)
    assert len({(row["source"], row["field"]) for row in rows}) == len(rows)
    assert reports.load_source("report-fields", App()) == rows


def test_report_fields_includes_its_own_schema(cli):
    assert cli("report", "report-fields", "--where", "source=report-fields") == [
        {"source": "report-fields", "group": "reference", "position": position, "field": field}
        for position, field in enumerate(("source", "group", "position", "field"), 1)
    ]


def test_report_fields_discovers_datasets_with_a_named_field(cli):
    assert cli("report", "report-fields", "--where", "field=symbol", "--fields", "source") == [
        {"source": source} for source, schema in reports.SOURCES.items() if "symbol" in schema
    ]


def test_report_fields_summarizes_schema_sizes(cli):
    assert cli("summarize", "report-fields", "--group-by", "source", "--metric", "fields=count") == [
        {"source": source, "fields": len(schema)} for source, schema in reports.SOURCES.items()
    ]


def test_report_fields_description_does_not_load_catalog(cli, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Describing fields must not load data")

    monkeypatch.setattr(reports, "load_source", forbidden)
    assert cli("report", "report-fields", "--describe") == {
        "source": "report-fields",
        "fields": ["source", "group", "position", "field"],
    }
