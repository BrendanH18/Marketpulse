"""Offline watchlist/alert productivity against fictional saved data."""

import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.models import Alert


@pytest.fixture
def cli(tracker, monkeypatch):
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    monkeypatch.setenv("COLUMNS", "160")
    runner = CliRunner()
    return lambda *args: runner.invoke(main, list(args), catch_exceptions=False)


def test_watch_search_pages_count_and_sort_are_offline_and_keep_saved_order(cli, store, fake):
    store.add_watch(["ZETA.TO", "ALPHA", "BETA.TO", "GAMMA"])
    assert json.loads(cli("watch", "list", "--search", ".to", "--json").output) == ["ZETA.TO", "BETA.TO"]
    page = cli("watch", "list", "--search", ".TO", "--offset", "1", "--limit", "1", "--json")
    assert json.loads(page.output) == ["BETA.TO"]
    assert cli("watch", "list", "--search", ".to", "--offset", "99", "--count").output.strip() == "2"
    assert json.loads(cli("watch", "list", "--alphabetical", "--limit", "2", "--json").output) == ["ALPHA", "BETA.TO"]
    assert store.watchlist() == ["ZETA.TO", "ALPHA", "BETA.TO", "GAMMA"]
    assert "BETA.TO" in cli("watch", "list", "--search", "beta").output
    assert "ZETA.TO" in cli("watch", "list", "--offset", "0").output
    assert "ZETA.TO" in cli("watch", "list", "--search", "").output
    assert cli("watch", "list", "--search", "absent", "--count").output.strip() == "0"
    assert json.loads(cli("watch", "list", "--offset", "99", "--json").output) == []
    assert cli("watch", "list", "--limit", "0").exit_code == 2
    assert cli("watch", "list", "--offset", "-1").exit_code == 2
    assert fake.calls == []


def test_alert_show_includes_full_note_and_history_and_masks_threshold(cli, store, fake):
    saved = store.add_alert(
        Alert("FICTION.TO", "above", 123.45, note="Fictional é 東京 [bold]", triggered_at="2024-01-01")
    )
    row = json.loads(cli("alerts", "show", str(saved.id), "--json").output)
    assert row["note"] == saved.note and row["triggered_at"] == saved.triggered_at
    assert row["state"] == "triggered" and row["threshold"] == 123.45
    output = cli("alerts", "show", str(saved.id)).output
    assert saved.note in output and "123.45" in output and "triggered_at" in output
    assert cli("config", "set", "privacy", "true").exit_code == 0
    hidden = cli("alerts", "show", str(saved.id)).output
    assert "123.45" not in hidden and "••••" in hidden
    assert cli("alerts", "show", "999").exit_code == 1
    assert cli("alerts", "show", "0").exit_code == 2
    assert fake.calls == []


def test_alert_edit_changes_criteria_and_note_preserving_state_and_trigger(cli, store, fake):
    saved = store.add_alert(Alert("FICTION.TO", "above", 100, note="old", active=False, triggered_at="2024-01-01"))
    result = cli(
        "alerts", "edit", str(saved.id), "--condition", "BELOW", "--threshold", "90", "--note", "Fictional 東京"
    )
    assert result.exit_code == 0
    alert = store.alerts()[0]
    assert (alert.symbol, alert.condition, alert.threshold, alert.note) == ("FICTION.TO", "below", 90, "Fictional 東京")
    assert not alert.active and alert.triggered_at == saved.triggered_at
    assert cli("alerts", "edit", str(saved.id), "--note", "").exit_code == 0
    alert = store.alerts()[0]
    assert alert.note == "" and not alert.active and alert.triggered_at == saved.triggered_at
    assert fake.calls == []


@pytest.mark.parametrize("threshold", ["nan", "inf", "-inf", "0", "-10"])
def test_invalid_alert_edit_is_atomic(cli, store, fake, threshold):
    saved = store.add_alert(Alert("FICTION.TO", "above", 100, note="old"))
    result = cli("alerts", "edit", str(saved.id), "--threshold", threshold, "--note", "new")
    assert result.exit_code == 1 and "finite and positive" in result.output
    assert store.alerts() == [saved]
    assert fake.calls == []


def test_alert_edit_requires_fields_and_existing_id(cli, store, fake):
    assert cli("alerts", "edit", "999", "--note", "new").exit_code == 1
    assert cli("alerts", "edit", "999").exit_code == 2
    assert cli("alerts", "edit", "999", "--condition", "invalid").exit_code == 2
    assert store.alerts() == [] and fake.calls == []


def test_alert_condition_filter_and_count_compose(cli, store, fake):
    saved = store.add_alert(Alert("FICTION.TO", "below", 90, active=False))
    store.add_alert(Alert("FICTION.TO", "above", 150))
    store.add_alert(Alert("OTHER", "below", 90))
    args = ("alerts", "list", "--symbol", "fiction.to", "--condition", "BELOW", "--state", "paused")
    rows = json.loads(cli(*args, "--json").output)
    assert len(rows) == 1 and rows[0]["id"] == saved.id
    assert cli(*args, "--count").output.strip() == "1"
    assert cli("alerts", "list", "--condition", "up_pct", "--count").output.strip() == "0"
    assert "No alerts match" in cli("alerts", "list", "--condition", "up_pct").output
    assert fake.calls == []


def test_legacy_nonfinite_alert_show_uses_json_null_and_can_be_repaired(cli, store, fake):
    store._exec("INSERT INTO alerts(symbol, condition, threshold) VALUES ('FICTION', 'above', ?)", (float("inf"),))
    row = json.loads(cli("alerts", "list", "--json").output)[0]
    shown = json.loads(cli("alerts", "show", str(row["id"]), "--json").output)
    assert shown["threshold"] is None and shown["state"] == "paused"
    assert cli("alerts", "edit", str(row["id"]), "--threshold", "100").exit_code == 0
    repaired = store.alerts()[0]
    assert repaired.threshold == 100 and not repaired.active
    assert fake.calls == []
