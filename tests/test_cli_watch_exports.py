"""Offline watchlist and alert exports with fictional saved metadata."""

import csv
import io
import json
from dataclasses import fields

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Alert


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    runner = CliRunner()
    return lambda *args: runner.invoke(main, list(args), catch_exceptions=False)


def test_watch_csv_preserves_saved_positions_and_escaping(cli, store, fake):
    store.add_watch(["ZETA.TO", "ALPHA", "BETA.TO"])
    result = cli("watch", "list", "--csv", "--alphabetical", "--offset", "1")
    assert result.exit_code == 0
    assert list(csv.DictReader(io.StringIO(result.output))) == [
        {"position": "3", "symbol": "BETA.TO"},
        {"position": "1", "symbol": "ZETA.TO"},
    ]
    assert store.watchlist() == ["ZETA.TO", "ALPHA", "BETA.TO"]
    assert fake.calls == []


def test_watch_descending_exclusions_pages_and_counts(cli, store, fake):
    store.add_watch(["ZETA.TO", "ALPHA", "BETA.TO", "GAMMA"])
    args = ("watch", "list", "--exclude-symbol", " alpha ", "--exclude-symbol", "gamma", "--descending")
    page = json.loads(cli(*args, "--json", "--page-info", "--limit", "1").output)
    assert page == {"total": 2, "offset": 0, "limit": 1, "returned": 1, "next_offset": 1, "items": ["BETA.TO"]}
    last = json.loads(cli(*args, "--json", "--page-info", "--offset", "1").output)
    assert last == {"total": 2, "offset": 1, "limit": None, "returned": 1, "next_offset": None, "items": ["ZETA.TO"]}
    assert cli(*args, "--count", "--limit", "1", "--offset", "99").output.strip() == "2"
    assert "BETA.TO" in cli("watch", "list", "--descending").output
    assert "ALPHA" not in cli("watch", "list", "--exclude-symbol", "alpha").output
    assert store.watchlist() == ["ZETA.TO", "ALPHA", "BETA.TO", "GAMMA"]
    assert fake.calls == []


def test_watch_empty_page_and_header(cli, store, fake):
    assert cli("watch", "list", "--csv").output.strip() == "position,symbol"
    empty = json.loads(cli("watch", "list", "--json", "--page-info", "--offset", "99").output)
    assert empty == {"total": 0, "offset": 99, "limit": None, "returned": 0, "next_offset": None, "items": []}
    assert fake.calls == []


@pytest.mark.parametrize("group", ["watch", "alerts"])
@pytest.mark.parametrize("options", [("--json", "--csv"), ("--json", "--count"), ("--csv", "--count")])
def test_conflicting_outputs_fail_before_network(cli, fake, group, options):
    result = cli(group, "list", *options)
    assert result.exit_code == 2 and "Choose one" in result.output
    assert fake.calls == []


@pytest.mark.parametrize("options", [("--page-info",), ("--page-info", "--csv"), ("--page-info", "--count")])
def test_watch_page_info_requires_json(cli, fake, options):
    result = cli("watch", "list", *options)
    assert result.exit_code == 2 and "requires --json" in result.output
    assert fake.calls == []


@pytest.fixture
def alerts(store):
    return [
        store.add_alert(Alert("ZETA.TO", "above", 120, note="Fictional, é\nsecond line")),
        store.add_alert(Alert("ALPHA", "below", 90, note="Fictional 東京", active=False)),
        store.add_alert(Alert("ZETA.TO", "above", 150, note="other", triggered_at="2024-01-01")),
    ]


def test_alert_csv_metadata_roundtrips_note_and_state(cli, store, fake, alerts):
    result = cli("alerts", "list", "--csv", "--sort", "id")
    reader = csv.DictReader(io.StringIO(result.output))
    rows = list(reader)
    assert reader.fieldnames == [field.name for field in fields(Alert)] + ["state"]
    assert [row["id"] for row in rows] == [str(a.id) for a in alerts]
    assert [row["state"] for row in rows] == ["armed", "paused", "triggered"]
    assert rows[0]["note"] == "Fictional, é\nsecond line"
    assert rows[0]["threshold"] == "120.0"
    assert fake.calls == []


def test_alert_search_and_filter_count_before_paging(cli, store, fake, alerts):
    result = cli("alerts", "list", "--search", "FICTIONAL", "--state", "armed", "--json")
    assert [row["id"] for row in json.loads(result.output)] == [alerts[0].id]
    assert len(json.loads(cli("alerts", "list", "--search", "zeta.to", "--json").output)) == 2
    assert json.loads(cli("alerts", "list", "--search", "東京", "--json").output)[0]["id"] == alerts[1].id
    assert (
        cli("alerts", "list", "--search", "fictional", "--count", "--limit", "1", "--offset", "99").output.strip()
        == "2"
    )
    assert "No alerts match" in cli("alerts", "list", "--search", "absent").output
    assert fake.calls == []


@pytest.mark.parametrize(
    ("sort", "indices"), [("id", [0, 1, 2]), ("symbol", [1, 0, 2]), ("state", [0, 1, 2]), ("condition", [0, 2, 1])]
)
def test_alert_sort_stable_id_ties_reverse_and_paging(cli, store, fake, alerts, sort, indices):
    args = ("alerts", "list", "--sort", sort, "--json")
    assert [row["id"] for row in json.loads(cli(*args).output)] == [alerts[i].id for i in indices]
    rows = json.loads(cli(*args, "--descending", "--offset", "1", "--limit", "1").output)
    assert [row["id"] for row in rows] == [alerts[list(reversed(indices))[1]].id]
    assert fake.calls == []


def test_alert_default_reverse_empty_pages_and_csv_header(cli, store, fake, alerts):
    rows = json.loads(cli("alerts", "list", "--json", "--descending").output)
    assert [row["id"] for row in rows] == [a.id for a in reversed(store.alerts())]
    assert json.loads(cli("alerts", "list", "--json", "--offset", "99").output) == []
    result = cli("alerts", "list", "--csv", "--offset", "99")
    assert list(csv.DictReader(io.StringIO(result.output))) == []
    assert "threshold" in result.output and "state" in result.output
    assert fake.calls == []


@pytest.mark.parametrize("options", [("--limit", "0"), ("--offset", "-1"), ("--sort", "invalid")])
def test_invalid_alert_paging_and_sort(cli, fake, options):
    assert cli("alerts", "list", *options).exit_code == 2
    assert fake.calls == []


def test_legacy_infinite_threshold_remains_exportable(cli, store, fake):
    store._exec("INSERT INTO alerts(symbol, condition, threshold) VALUES ('FICTION', 'above', ?)", (float("inf"),))
    assert json.loads(cli("alerts", "list", "--json").output)[0]["threshold"] is None
    row = list(csv.DictReader(io.StringIO(cli("alerts", "list", "--csv").output)))[0]
    assert row["threshold"] == "" and row["state"] == "paused"
    assert fake.calls == []
