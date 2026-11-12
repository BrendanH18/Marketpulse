"""Calendar selections and count summaries read fictional snapshots without mutations."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.db import Snapshot


@pytest.fixture
def browse(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setattr("marketpulse.cli.base.Config.load", lambda: tracker.config)
    source = [
        Snapshot("2023-12-31", 100, 80, 70, "CAD", {}),
        Snapshot("2024-01-01", 120, 90, 75, "CAD", {}),
        Snapshot("2024-01-02", 120, 90, 75, "CAD", {}),
        Snapshot("2024-04-01", 110, 95, 80, "USD", {}),
        Snapshot("2024-04-02", 100, 90, 75, "USD", {}),
        Snapshot("2024-07-01", 130, 95, 80, "CAD", {}),
    ]
    store.upsert_snapshots(source)
    fake.offline = True

    def invoke(*args, output="--json"):
        result = CliRunner().invoke(main, ["snapshots", *args, *([output] if output else [])], catch_exceptions=False)
        assert fake.calls == []
        assert store.snapshots() == source
        return result

    return invoke


def payload(browse, *args):
    result = browse(*args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_quarter_selection_composes_before_page(browse):
    page = payload(browse, "--quarter", "2024-Q2", "--sort", "date", "--limit", "1", "--page-info")
    assert page["total"] == 2
    assert page["rows"][0]["date"] == "2024-04-01"
    assert payload(browse, "--quarter", "2024-Q2", "--month", "2024-01") == []


def test_repeatable_weekdays_case_insensitive(browse):
    rows = payload(browse, "--weekday", "MON", "--weekday", "tue", "--exclude-date", "2024-07-01")
    assert [r["date"] for r in rows] == ["2024-01-01", "2024-01-02", "2024-04-01", "2024-04-02"]


def test_repeatable_dates_preserve_change_baseline(browse):
    rows = payload(browse, "--on", "2024-01-01", "--on", "2024-04-02", "--on", "2024-01-01")
    assert [r["change"] for r in rows] == [20, -10]


def test_currency_exclusions_and_known_change(browse):
    rows = payload(browse, "--exclude-currency", " usd ", "--known-change-only")
    assert [r["date"] for r in rows] == ["2024-01-01", "2024-01-02"]
    assert [r["change"] for r in rows] == [20, 0]
    assert payload(browse, "--exclude-currency", "CAD", "--exclude-currency", "USD") == []


def test_earliest_json_csv_human_and_missing(browse, tracker):
    row = payload(browse, "--since", "2024-01-02", "--earliest")
    assert row["date"] == "2024-01-02"
    result = browse("--earliest", output="--csv")
    assert [r["date"] for r in csv.DictReader(io.StringIO(result.output))] == ["2023-12-31"]
    tracker.config.privacy = True
    result = browse("--earliest", output=None)
    assert result.exit_code == 0 and "100.00" not in result.output
    assert browse("--earliest", "--since", "2030-01-01").exit_code == 1


@pytest.mark.parametrize(
    "group,expected",
    [
        ("year", [("2023", 1), ("2024", 5)]),
        ("month", [("2023-12", 1), ("2024-01", 2), ("2024-04", 2), ("2024-07", 1)]),
        ("quarter", [("2023-Q4", 1), ("2024-Q1", 2), ("2024-Q2", 2), ("2024-Q3", 1)]),
        ("currency", [("CAD", 4), ("USD", 2)]),
    ],
)
def test_all_summary_dimensions(browse, group, expected):
    rows = payload(browse, "--summary", group)
    assert [(row["group"], row["count"]) for row in rows] == expected


def test_summary_filter_csv_human_and_empty(browse, tracker):
    result = browse("--summary", "currency", "--known-change-only", output="--csv")
    assert list(csv.DictReader(io.StringIO(result.output))) == [
        {"group": "CAD", "count": "2"},
        {"group": "USD", "count": "1"},
    ]
    tracker.config.privacy = True
    result = browse("--summary", "quarter", output=None)
    assert result.exit_code == 0 and "2024-Q1" in result.output
    assert payload(browse, "--summary", "month", "--since", "2030-01-01") == []


@pytest.mark.parametrize("quarter", ["2024-Q0", "2024-Q5", "0000-Q1", "2024-q1", "2024-01", "bad"])
def test_invalid_quarters(browse, quarter):
    assert browse("--quarter", quarter).exit_code == 2


@pytest.mark.parametrize(
    "args",
    [
        ["--on", "2024-02-30"],
        ["--weekday", "bad"],
        ["--exclude-currency", " "],
        ["--known-change-only", "--unknown-change-only"],
        ["--earliest", "--latest"],
        ["--earliest", "--count"],
        ["--earliest", "--limit", "1"],
        ["--earliest", "--offset", "0"],
        ["--earliest", "--sort", "date"],
        ["--summary", "month", "--count"],
        ["--summary", "month", "--latest"],
        ["--summary", "month", "--earliest"],
        ["--summary", "month", "--limit", "1"],
        ["--summary", "month", "--descending"],
        ["--summary", "month", "--page-info"],
    ],
)
def test_invalid_combinations(browse, args):
    assert browse(*args).exit_code == 2


def test_currency_exclusion_normalizes_saved_currency(store, tracker, fake, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    source = [Snapshot("2024-01-01", 100, 80, 70, "usd", {})]
    store.upsert_snapshots(source)
    fake.offline = True
    result = CliRunner().invoke(main, ["snapshots", "--exclude-currency", "USD", "--json"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == []
    assert store.snapshots() == source
    assert fake.calls == []
