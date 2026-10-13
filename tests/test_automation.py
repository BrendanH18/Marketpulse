import json
import sqlite3
from datetime import date

import pytest
from click.testing import CliRunner

from marketpulse.automation import run_cycle
from marketpulse.cli import main
from marketpulse.desktop import snapshot
from marketpulse.models import Account, Alert, Transaction, TxnType


def holding(store):
    account = store.add_account(Account(name="Investing"))
    store.add_transaction(
        Transaction(account_id=account.saved_id, type=TxnType.BUY, symbol="AAPL", quantity=2, price=150, currency="USD")
    )
    return account


def test_cycle_records_snapshot_backs_up_and_checks_alert_only_symbols(tracker, fake, notifications):
    holding(tracker.store)
    fake.set_quote("MSFT", 400)
    tracker.store.add_alert(Alert("MSFT", "above", 390))
    report = run_cycle(tracker, fresh=True).report
    assert report["snapshot_date"] == date.today().isoformat()
    assert report["backup"].endswith("daily.db")
    assert report["fired"] == ["MSFT ≥ 390.00"]
    assert len(notifications) == 1
    assert tracker.store.latest_snapshot().net_worth == pytest.approx(540)
    run_cycle(tracker, fresh=True)
    assert len(tracker.store.snapshots()) == 1
    assert len(tracker.store.backups()) == 1
    assert len(notifications) == 1
    assert json.loads(tracker.store.get_meta("automation_last_run"))["errors"] == []


def test_stale_cycle_does_not_record_snapshot_or_fire_alert(tracker, fake, notifications):
    holding(tracker.store)
    tracker.valuation(record=False)  # populate persisted quote cache
    fake.offline = True
    tracker.store.add_alert(Alert("AAPL", "above", 100))
    report = run_cycle(tracker, fresh=True).report
    assert report["stale"] is True
    assert report["snapshot_date"] is None
    assert report["fired"] == []
    assert notifications == []
    assert tracker.store.snapshots() == []


def test_backup_failure_does_not_hide_valuation(tracker, monkeypatch):
    holding(tracker.store)

    def fail_backup():
        raise sqlite3.OperationalError("disk full")

    monkeypatch.setattr(tracker.store, "auto_backup", fail_backup)
    cycle = run_cycle(tracker)
    assert cycle.view.net_worth == pytest.approx(540)
    assert cycle.report["errors"] == ["Backup failed: disk full"]


def test_desktop_bridge_reports_missing_prices(tracker):
    acct = holding(tracker.store)
    tracker.store.add_transaction(
        Transaction(account_id=acct.saved_id, type=TxnType.BUY, symbol="UNKNOWN", quantity=1, price=50, currency="CAD")
    )
    payload = snapshot(tracker)
    assert payload["version"] == 1
    assert payload["demo"] is False
    assert payload["status"]["net_worth"] == pytest.approx(540)
    assert "Excluded from totals: UNKNOWN" in payload["warnings"]
    assert next(p for p in payload["positions"] if p["symbol"] == "UNKNOWN")["value"] is None
    assert payload["activity"][0]["type"] == "BUY"
    json.dumps(payload, allow_nan=False)


def test_demo_never_opens_real_tracker(monkeypatch, tmp_path, notifications):
    def fail_open(*args, **kwargs):
        raise AssertionError("Real portfolio must not be opened")

    monkeypatch.setattr("marketpulse.services.Tracker.open", fail_open)
    result = CliRunner().invoke(main, ["desktop", "snapshot", "--demo"], catch_exceptions=False)
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["demo"] is True
    assert len(payload["positions"]) == 5
    assert len(payload["status"]["history"]) == 181
    assert not (tmp_path / "data").exists()
    assert notifications == []
