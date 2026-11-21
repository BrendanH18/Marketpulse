"""Import reference reports use the same mappings and headers as the CSV importer."""

import io
import json

import pytest
from click.testing import CliRunner

from marketpulse import brokers, csvio
from marketpulse.cli import main, report_integrations
from marketpulse.cli.base import App


def test_known_broker_codes_match_converter_behavior():
    rows = report_integrations.load_source("broker-transaction-codes", App())
    profiles = {profile.name: profile for profile in brokers.PROFILES if profile.convert is not None}
    assert {row["profile"] for row in rows} == {"questrade", "wealthsimple"}
    assert len({(row["profile"], row["code"], row["action"]) for row in rows}) == len(rows)
    assert [(row["code"], row["action"], row["type"]) for row in rows if row["action"]] == [
        ("trades", "buy", "BUY"),
        ("trades", "sell", "SELL"),
    ]
    assert any(row["profile"] == "wealthsimple" and row["code"] == "FPLINT" for row in rows)

    for row in rows:
        sample = {row["column"]: row["code"], "description": "FICTIONAL - Bought 2 shares"}
        if row["action"]:
            sample["action"] = row["action"]
        convert = profiles[row["profile"]].convert
        assert convert is not None
        if row["outcome"] == "mapped":
            assert convert(sample)["type"] == row["type"]
            assert row["reason"] is None
        else:
            assert row["outcome"] == "skipped"
            with pytest.raises(brokers.RowError) as caught:
                convert(sample)
            assert caught.value.reason == row["reason"]
            assert row["type"] is None


def test_csv_catalog_follows_real_export_order_and_generic_rules(store):
    rows = report_integrations.load_source("transaction-csv-columns", App())
    exported = io.StringIO()
    csvio.export_transactions(store, exported)
    headers = csvio.read_headers(exported.getvalue())
    assert [row["position"] for row in rows] == list(range(1, len(headers) + 1))
    assert [row["column"] for row in rows] == headers
    assert [row["column"] for row in rows if row["required"]] == ["date", "type"]
    for row in rows:
        assert row["aliases"] == brokers._ALIASES[row["column"]]
        assert all(brokers.map_headers([alias])[row["column"]] == alias for alias in row["aliases"])
        remaining = [header for header in headers if header != row["column"]]
        source = io.StringIO(",".join(remaining) + "\n")
        if row["required"]:
            with pytest.raises(ValueError, match=f"required column\\(s\\): {row['column']}\\."):
                csvio.import_transactions(store, source, profile="generic")
        else:
            assert csvio.import_transactions(store, source, profile="generic").added == 0


@pytest.mark.parametrize("source", report_integrations.SOURCES)
def test_reference_reports_are_available_without_opening_a_tracker(monkeypatch, source):
    def forbid_saved_data(self):
        pytest.fail("reference report opened the tracker")

    monkeypatch.setattr(App, "tracker", property(forbid_saved_data))
    runner = CliRunner()
    report = runner.invoke(main, ["report", source])
    summary = runner.invoke(main, ["summarize", source, "--metric", "rows=count"])
    assert report.exit_code == 0, report.output
    assert summary.exit_code == 0, summary.output
    rows = json.loads(report.output)
    assert rows and all(tuple(row) == report_integrations.SOURCES[source] for row in rows)
    assert json.loads(summary.output) == [{"rows": len(rows)}]


def test_reference_presets_select_the_expected_rows():
    runner = CliRunner()

    def selected(source, preset):
        result = runner.invoke(main, ["report", source, "--preset", preset])
        assert result.exit_code == 0, result.output
        return json.loads(result.output)

    source = "transaction-csv-columns"
    assert [row["column"] for row in selected(source, "required")] == ["date", "type"]
    assert [row["column"] for row in selected(source, "optional")] == [
        column for column in csvio.EXPORT_COLUMNS if column not in {"date", "type"}
    ]
    assert [row["column"] for row in selected(source, "account-routing")] == ["account", "target_account"]

    source = "broker-transaction-codes"
    assert [row["action"] for row in selected(source, "trade-actions")] == ["buy", "sell"]
    assert all(row["type"] and row["reason"] is None for row in selected(source, "supported"))
    assert all(row["reason"] and row["type"] is None for row in selected(source, "skipped"))
