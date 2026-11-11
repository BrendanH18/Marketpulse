"""Saved-symbol selection and alert count summaries use only fictional metadata."""

import csv
import io
import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Alert


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))

    def forbidden(*args, **kwargs):
        raise AssertionError("saved inventory must not fetch prices")

    monkeypatch.setattr(tracker, "watchlist_quotes", forbidden)
    runner = CliRunner()
    return lambda *args: runner.invoke(main, list(args), catch_exceptions=False)


@pytest.fixture
def saved(store):
    store.add_watch(["ZETA", "ALPHA", "BETA", "GAMMA"])
    return [
        store.add_alert(Alert("ZETA", "above", 100, note="fictional entry")),
        store.add_alert(Alert("ZETA", "below", 50, note="fictional exit", active=False)),
        store.add_alert(Alert("BETA", "above", 90, note="ZETA only in note", triggered_at="2024-01-02T12:00:00Z")),
        store.add_alert(Alert("OTHER", "up_pct", 5, note="")),
    ]


@pytest.mark.parametrize(
    "options,expected",
    [
        (("--symbol", " zeta ", "--symbol", "beta"), ["ZETA", "BETA"]),
        (("--symbol", "AL"), []),
        (("--min-position", "2"), ["ALPHA", "BETA", "GAMMA"]),
        (("--max-position", "2"), ["ZETA", "ALPHA"]),
        (("--min-position", "2", "--max-position", "2"), ["ALPHA"]),
        (("--with-alert",), ["ZETA", "BETA"]),
        (("--without-alert",), ["ALPHA", "GAMMA"]),
    ],
)
def test_watch_selection(cli, store, fake, saved, options, expected):
    before = store.watchlist()
    result = cli("watch", "list", *options, "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == expected
    # Also prove that each filter alone implies offline in human output.
    assert cli("watch", "list", *options).exit_code == 0
    assert store.watchlist() == before
    assert fake.calls == []


def test_saved_position_precedes_order_and_paging(cli, saved):
    args = ("watch", "list", "--min-position", "2", "--max-position", "4", "--without-alert", "--alphabetical")
    page = json.loads(cli(*args, "--json", "--page-info", "--limit", "1").output)
    assert page == {"items": ["ALPHA"], "total": 2, "offset": 0, "limit": 1, "returned": 1, "next_offset": 1}
    assert cli(*args, "--count", "--offset", "99").output.strip() == "2"
    csv_rows = list(csv.DictReader(io.StringIO(cli(*args, "--csv", "--descending").output)))
    assert csv_rows == [{"position": "4", "symbol": "GAMMA"}, {"position": "2", "symbol": "ALPHA"}]


def test_watch_alert_membership_includes_paused_alerts(cli, store):
    store.add_watch(["ONLYPAUSED", "NONE"])
    store.add_alert(Alert("ONLYPAUSED", "above", 10, active=False))
    assert json.loads(cli("watch", "list", "--with-alert", "--json").output) == ["ONLYPAUSED"]


@pytest.mark.parametrize(
    "options,indices",
    [
        (("--symbols", " zeta ", "--symbols", "beta"), [2, 0, 1]),
        (("--exclude-state", "PAUSED", "--exclude-state", "triggered"), [3, 0]),
        (("--note", "ZETA"), [2]),
        (("--symbols", "zeta", "--exclude-state", "paused", "--note", "ENTRY"), [0]),
    ],
)
def test_alert_selection(cli, store, fake, saved, options, indices):
    before = store.alerts()
    rows = json.loads(cli("alerts", "list", *options, "--json").output)
    assert [row["id"] for row in rows] == [saved[i].id for i in indices]
    assert store.alerts() == before and fake.calls == []


@pytest.mark.parametrize(
    "group,expected",
    [
        ("symbol", [{"group": "BETA", "count": 1}, {"group": "OTHER", "count": 1}, {"group": "ZETA", "count": 2}]),
        (
            "state",
            [{"group": "armed", "count": 2}, {"group": "paused", "count": 1}, {"group": "triggered", "count": 1}],
        ),
        (
            "condition",
            [{"group": "above", "count": 2}, {"group": "below", "count": 1}, {"group": "up_pct", "count": 1}],
        ),
    ],
)
def test_summaries_before_paging_all_formats(cli, saved, fake, group, expected):
    args = ("alerts", "list", "--summary", group, "--offset", "99", "--limit", "1")
    assert json.loads(cli(*args, "--json").output) == expected
    csv_rows = list(csv.DictReader(io.StringIO(cli(*args, "--csv").output)))
    assert csv_rows == [{"group": row["group"], "count": str(row["count"])} for row in expected]
    assert "Matching alerts" in cli(*args).output
    assert fake.calls == []


def test_summary_respects_selection_and_empty_results(cli, saved):
    result = cli("alerts", "list", "--summary", "state", "--symbols", "ZETA", "--exclude-state", "armed", "--json")
    assert json.loads(result.output) == [{"group": "paused", "count": 1}]
    assert json.loads(cli("alerts", "list", "--summary", "symbol", "--note", "not present", "--json").output) == []
    assert (
        cli("alerts", "list", "--summary", "symbol", "--note", "not present", "--csv").output.strip() == "group,count"
    )


@pytest.mark.parametrize(
    "command,options",
    [
        ("watch", ("--symbol", " ")),
        ("watch", ("--min-position", "0")),
        ("watch", ("--max-position", "0")),
        ("watch", ("--min-position", "3", "--max-position", "2")),
        ("alerts", ("--symbols", " ")),
        ("alerts", ("--exclude-state", "bad")),
        ("alerts", ("--summary", "state", "--count")),
        ("alerts", ("--summary", "state", "--page-info", "--json")),
    ],
)
def test_invalid_options(cli, fake, command, options):
    assert cli(command, "list", *options).exit_code == 2
    assert fake.calls == []
