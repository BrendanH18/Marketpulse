"""Offline snapshot browsing; changes always use the complete recorded history."""

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
        Snapshot("2023-12-31", 100, 90, 80, "CAD", {}),
        Snapshot("2024-01-01", 120, 95, 82, "CAD", {}),
        Snapshot("2024-01-02", 120, 99, 85, "CAD", {}),
        Snapshot("2024-02-01", 110, 100, 90, "CAD", {}),
        Snapshot("2024-02-02", 105, 80, 70, "USD", {}),
        Snapshot("2024-02-03", 115, 83, 75, "USD", {}),
    ]
    store.upsert_snapshots(source)
    fake.offline = True

    def invoke(*args, json_output=True):
        result = CliRunner().invoke(
            main, ["snapshots", *args, *(["--json"] if json_output else [])], catch_exceptions=False
        )
        assert fake.calls == []
        assert store.snapshots() == source
        return result

    return invoke


def rows(browse, *args):
    result = browse(*args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_calendar_filters_and_original_changes(browse):
    assert len(rows(browse, "--year", "2024")) == 5
    january = rows(browse, "--year", "2024", "--month", "2024-01")
    assert [r["date"] for r in january] == ["2024-01-01", "2024-01-02"]
    assert january[0]["change"] == 20
    assert rows(browse, "--month", "2025-01") == []


@pytest.mark.parametrize(
    "field,key", [("date", "date"), ("net-worth", "net_worth"), ("book", "book"), ("contributions", "contributions")]
)
def test_order_and_reverse_with_forward_limit(browse, field, key):
    ascending = rows(browse, "--sort", field)
    descending = rows(browse, "--sort", field, "--descending")
    assert descending == list(reversed(ascending))
    assert [r[key] for r in ascending] == sorted(r[key] for r in ascending)
    assert rows(browse, "--sort", field, "--limit", "2") == ascending[:2]


def test_change_sort_unknown_always_last(browse):
    asc = rows(browse, "--sort", "change")
    desc = rows(browse, "--sort", "change", "--descending")
    assert [r["change"] for r in asc] == [-10, 0, 10, 20, None, None]
    assert [r["change"] for r in desc] == [20, 10, 0, -10, None, None]


def test_offset_page_metadata_and_legacy_limit(browse):
    all_rows = rows(browse)
    assert rows(browse, "--limit", "2") == all_rows[-2:]
    assert rows(browse, "--offset", "0", "--limit", "2") == all_rows[:2]
    assert rows(browse, "--offset", "2", "--limit", "2") == all_rows[2:4]
    page = rows(browse, "--month", "2024-02", "--page-info", "--offset", "1", "--limit", "1")
    assert page == {"rows": [all_rows[4]], "total": 3, "offset": 1, "limit": 1}
    empty = rows(browse, "--offset", "99", "--page-info")
    assert empty == {"rows": [], "total": 6, "offset": 99, "limit": None}


def test_inclusive_bounds_and_change_filters(browse):
    assert [r["net_worth"] for r in rows(browse, "--min-net-worth", "110", "--max-net-worth", "115")] == [110, 115]
    assert [r["change"] for r in rows(browse, "--changed-only")] == [20, -10, 10]
    assert [r["date"] for r in rows(browse, "--unchanged-only")] == ["2024-01-02"]
    result = browse("--changed-only", "--count", json_output=False)
    assert result.exit_code == 0 and result.output == "3\n"


def test_csv_and_private_human_output(browse, tracker):
    result = browse("--sort", "date", "--descending", "--offset", "1", "--limit", "1", "--csv", json_output=False)
    assert result.exit_code == 0
    assert list(csv.DictReader(io.StringIO(result.output)))[0]["date"] == "2024-02-02"
    tracker.config.privacy = True
    result = browse("--min-net-worth", "115", "--sort", "book", json_output=False)
    assert result.exit_code == 0 and "120.00" not in result.output and "115.00" not in result.output
    assert rows(browse, "--max-net-worth", "100")[0]["net_worth"] == 100


@pytest.mark.parametrize(
    "args",
    [
        ["--month", "2024-1"],
        ["--month", "2024-13"],
        ["--month", "0000-01"],
        ["--year", "0"],
        ["--year", "2023", "--month", "2024-01"],
        ["--min-net-worth", "nan"],
        ["--max-net-worth", "inf"],
        ["--min-net-worth", "200", "--max-net-worth", "100"],
        ["--changed-only", "--unchanged-only"],
        ["--offset", "-1"],
        ["--latest", "--sort", "date"],
        ["--latest", "--descending"],
        ["--latest", "--offset", "0"],
        ["--count", "--sort", "book"],
        ["--count", "--offset", "0"],
        ["--count", "--descending"],
        ["--count", "--page-info"],
        ["--page-info"],
    ],
)
def test_invalid_browsing_options(browse, args):
    result = browse(*args, json_output=False)
    assert result.exit_code == 2, result.output
