"""Offline CLI automation, using only fictional watchlists, alerts and CSV rows."""

import json
from pathlib import Path

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


def test_offline_watchlist_empty_and_ordered(cli, store, fake):
    assert json.loads(cli("watch", "list", "--json").output) == []
    assert "empty" in cli("watch", "list", "--offline").output
    store.add_watch(["XEQT.TO", "AAPL", "NVDA"])
    assert json.loads(cli("watch", "list", "--json").output) == ["XEQT.TO", "AAPL", "NVDA"]
    output = cli("watch", "list", "--offline").output
    assert "Position" in output and output.index("XEQT.TO") < output.index("AAPL") < output.index("NVDA")
    assert store.accounts() == [] and fake.calls == []


def test_watch_move_uses_one_based_positions_and_preserves_membership(cli, store, fake):
    store.add_watch(["XEQT.TO", "AAPL", "NVDA"])
    assert cli("watch", "move", " nvda ", "--to", "1").exit_code == 0
    assert store.watchlist() == ["NVDA", "XEQT.TO", "AAPL"]
    assert cli("watch", "move", "NVDA", "--to", "3").exit_code == 0
    assert store.watchlist() == ["XEQT.TO", "AAPL", "NVDA"]
    assert cli("watch", "move", "AAPL", "--to", "2").exit_code == 0
    before = store.watchlist()
    for symbol, position in [("AAPL", "0"), ("AAPL", "4"), ("NOPE", "1")]:
        assert cli("watch", "move", symbol, "--to", position).exit_code != 0
        assert store.watchlist() == before
    assert fake.calls == []


def test_alert_filters_compose_with_json_and_paused_takes_precedence(cli, store, fake):
    armed = store.add_alert(Alert("AAPL", "above", 100, note="Fictional é 東京"))
    store.add_alert(Alert("NVDA", "below", 90, triggered_at="2024-01-01T12:00:00"))
    paused = store.add_alert(Alert("AAPL", "above", 150, active=False, triggered_at="2024-01-02T12:00:00"))
    assert json.loads(cli("alerts", "list", "--symbol", "aapl", "--state", "ARMED", "--json").output) == [
        {
            "id": armed.id,
            "symbol": "AAPL",
            "condition": "above",
            "threshold": 100,
            "note": "Fictional é 東京",
            "active": True,
            "triggered_at": "",
            "state": "armed",
        }
    ]
    rows = json.loads(cli("alerts", "list", "--state", "paused", "--json").output)
    assert [row["id"] for row in rows] == [paused.id]
    assert "paused" in cli("alerts", "list", "--state", "paused").output
    assert len(json.loads(cli("alerts", "list", "--state", "triggered", "--json").output)) == 1
    assert json.loads(cli("alerts", "list", "--symbol", "NOPE", "--json").output) == []
    assert "No alerts match" in cli("alerts", "list", "--symbol", "NOPE").output
    assert cli("alerts", "list", "--state", "invalid").exit_code == 2
    assert fake.calls == []


def test_alert_pause_resume_preserves_latch_and_rearm_allows_next_fresh_trigger(cli, store, fake, notifications):
    saved = store.add_alert(Alert("AAPL", "above", 100, note="Fictional alert", triggered_at="2024-01-02T12:00:00"))
    alert_id = str(saved.saved_id)
    assert cli("alerts", "pause", alert_id).exit_code == 0
    assert not store.alerts()[0].active
    assert cli("alerts", "resume", alert_id).exit_code == 0
    alert = store.alerts()[0]
    assert alert.active and alert.triggered_at == saved.triggered_at
    assert (alert.symbol, alert.condition, alert.threshold, alert.note) == ("AAPL", "above", 100, "Fictional alert")
    assert fake.calls == []
    assert "No alerts fired" in cli("alerts", "check").output
    assert notifications == []
    assert cli("alerts", "pause", alert_id).exit_code == 0
    assert cli("alerts", "rearm", alert_id).exit_code == 0
    assert store.alerts()[0].active and not store.alerts()[0].triggered_at
    assert "Fired" in cli("alerts", "check").output
    assert len(notifications) == 1


@pytest.mark.parametrize("command", ["pause", "resume", "rearm"])
def test_missing_alert_controls_fail_without_creating_anything(cli, store, fake, command):
    result = cli("alerts", command, "999")
    assert result.exit_code == 1 and "No alert #999" in result.output
    assert cli("alerts", command, "0").exit_code == 2
    assert store.alerts() == [] and fake.calls == []


def test_legacy_invalid_alerts_remain_inspectable_but_cannot_be_reactivated(cli, store, fake):
    store._exec("INSERT INTO alerts(symbol, condition, threshold) VALUES ('LEGACY', 'above', ?)", (float("inf"),))
    row = json.loads(cli("alerts", "list", "--json").output)[0]
    assert row["threshold"] is None and row["state"] == "paused"
    for command in ("resume", "rearm"):
        result = cli("alerts", command, str(row["id"]))
        assert result.exit_code == 1 and "finite and positive" in result.output
    assert cli("alerts", "pause", str(row["id"])).exit_code == 0
    assert not store.alerts()[0].active and fake.calls == []


def test_backup_json_lists_full_paths_sizes_reasons_and_times(cli, store, fake):
    assert json.loads(cli("backup", "list", "--json").output) == []
    saved = store.backup(reason="manual")
    result = cli("backup", "list", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == [
        {
            "file": saved.name,
            "path": str(saved.resolve()),
            "reason": "manual",
            "size_bytes": saved.stat().st_size,
            "taken_at": store.backup_time(saved).isoformat(),
        }
    ]
    assert store.backups() == [saved] and fake.calls == []


def test_import_json_keeps_all_diagnostics_and_preview_matches_import(cli, store, tmp_path, fake):
    source = tmp_path / "fictional.csv"
    valid = "2024-01-02,Fictional é 東京,deposit,123.45,CAD\n"
    source.write_text(
        "date,account,type,amount,currency\n" + valid * 7 + "2024-13-01,Fictional é 東京,deposit,10,CAD\n" * 18,
        encoding="utf-8",
    )
    preview = cli("import", str(source), "--dry-run", "--json")
    assert preview.exit_code == 0
    expected = json.loads(preview.output)
    assert expected["dry_run"] and expected["backup"] is None
    assert expected["added"] == 7 and expected["duplicates"] == 0 and len(expected["issues"]) == 18
    assert expected["accounts_created"] == ["Fictional é 東京"]
    assert store.accounts() == [] and store.transactions() == [] and store.backups() == []
    imported = cli("import", str(source), "--json")
    assert imported.exit_code == 0
    actual = json.loads(imported.output)
    assert not actual["dry_run"] and Path(actual["backup"]).is_file()
    for key in ("added", "duplicates", "issues", "duplicate_rows", "accounts_created", "fingerprint"):
        assert actual[key] == expected[key]
    repeated = json.loads(cli("import", str(source), "--json").output)
    assert repeated["added"] == 0 and repeated["duplicates"] == 7 and len(repeated["issues"]) == 18
    assert len(repeated["duplicate_rows"]) == 7
    assert len(store.transactions()) == 7 and fake.calls == []


@pytest.mark.parametrize("options", [("--dry-run",), ("--dry-run", "--json"), ("--json",)])
def test_import_preview_and_json_do_not_silently_create_default_accounts(cli, store, tmp_path, options):
    source = tmp_path / "unnamed.csv"
    source.write_text("date,type,amount\n2024-01-02,deposit,100\n", encoding="utf-8")
    result = cli("import", str(source), *options)
    assert result.exit_code == 1 and "No active account" in result.output
    assert store.accounts() == [] and store.transactions() == []
    assert cli("accounts", "add", "Fictional Cash").exit_code == 0
    success = cli("import", str(source), *options)
    assert success.exit_code == 0
    if "--json" in options:
        assert json.loads(success.output)["added"] == 1
