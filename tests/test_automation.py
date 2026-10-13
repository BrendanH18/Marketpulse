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


@pytest.mark.parametrize(("held", "watched"), [(True, False), (False, True), (True, True)])
def test_alert_reuses_fresh_portfolio_quote_after_redundant_request_failure(
    tracker, fake, notifications, monkeypatch, held, watched
):
    from marketpulse.market import SPARK_URL, MarketError

    if held:
        holding(tracker.store)
    tracker.store.add_alert(Alert("AAPL", "above", 150))
    if watched:
        tracker.store.add_watch(["AAPL"])
    original = fake.get_json
    requests = 0

    def fail_repeat(url, params):
        nonlocal requests
        if url == SPARK_URL and "AAPL" in params["symbols"].split(","):
            requests += 1
            if requests > 1:
                raise MarketError("transient refresh failure")
        return original(url, params)

    monkeypatch.setattr(fake, "get_json", fail_repeat)
    report = run_cycle(tracker, fresh=True).report
    assert report["fired"] == ["AAPL ≥ 150.00"]
    assert len(notifications) == 1
    assert requests == (2 if held and watched else 1)


def test_desktop_bridge_includes_all_snapshot_history(tracker):
    from marketpulse.db import Snapshot

    for day, currency in [
        ("1900-01-01", "CAD"),
        ("2010-01-01", "CAD"),
        (date.today().isoformat(), "CAD"),
        ("2000-01-01", "USD"),
    ]:
        tracker.store.upsert_snapshot(Snapshot(day, 100, 90, 90, currency, {}))
    payload = snapshot(tracker)
    assert [s["date"] for s in payload["status"]["history"]] == ["1900-01-01", "2010-01-01", date.today().isoformat()]
    # The existing menu-bar status contract still defaults to thirty days.
    assert [s["date"] for s in tracker.status_payload()["history"]] == [date.today().isoformat()]


def test_legacy_invalid_alerts_do_not_stop_desktop_refresh(tracker, notifications):
    tracker.store._exec("INSERT INTO alerts(symbol, condition, threshold) VALUES ('AAPL', 'above', 0)")
    tracker.store._exec("INSERT INTO alerts(symbol, condition, threshold) VALUES ('', 'above', 100)")
    tracker.store.add_alert(Alert("AAPL", "above", 150))
    payload = snapshot(tracker)
    assert payload["automation"]["fired"] == ["AAPL ≥ 150.00"]
    assert len(notifications) == 1
    assert sum(a["active"] for a in payload["alerts"]) == 1
    json.dumps(payload, allow_nan=False)


def test_unquotable_symbol_is_reported_but_does_not_fail_one_shot_run(tracker, monkeypatch):
    holding(tracker.store)
    tracker.store.add_watch(["DELISTED"])
    report = run_cycle(tracker, fresh=True).report
    assert report["errors"] == []
    assert report["quote_errors"] == ["DELISTED: symbol not found"]
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    result = CliRunner().invoke(main, ["automation", "run", "--once", "--json", "--quiet"], catch_exceptions=False)
    assert result.exit_code == 0
    assert json.loads(result.output)["quote_errors"] == ["DELISTED: symbol not found"]


def test_failed_backup_still_fails_one_shot_run(tracker, monkeypatch):
    holding(tracker.store)

    def fail_backup():
        raise OSError("disk full")

    monkeypatch.setattr(tracker.store, "auto_backup", fail_backup)
    monkeypatch.setattr("marketpulse.services.Tracker.open", classmethod(lambda cls, config=None: tracker))
    result = CliRunner().invoke(main, ["automation", "run", "--once", "--json", "--quiet"], catch_exceptions=False)
    assert result.exit_code == 1
    assert json.loads(result.output)["errors"] == ["Backup failed: disk full"]


def test_desktop_bridge_hides_archived_accounts(tracker):
    store = tracker.store
    active = holding(store)
    old = store.add_account(Account(name="Old RRSP"))
    store.add_transaction(
        Transaction(account_id=old.saved_id, type=TxnType.BUY, symbol="AAPL", quantity=1, price=150, currency="USD")
    )
    store.add_transaction(
        Transaction(
            account_id=active.saved_id,
            type=TxnType.TRANSFER,
            symbol="AAPL",
            quantity=1,
            price=150,
            currency="USD",
            target_account_id=old.saved_id,
        )
    )
    old.archived = True
    store.update_account(old)
    payload = snapshot(tracker)
    assert [a["name"] for a in payload["accounts"]] == ["Investing"]
    assert {p["account_id"] for p in payload["positions"]} == {active.saved_id}
    assert {t["account_id"] for t in payload["activity"]} == {active.saved_id}
    assert [a["name"] for a in payload["status"]["accounts"]] == ["Investing"]
    # The active account's own transfer keeps its destination; hidden value stays in totals and is flagged.
    assert next(t for t in payload["activity"] if t["type"] == "TRANSFER")["target_account"] == "Old RRSP"
    assert payload["status"]["net_worth"] == pytest.approx(810)  # 3 AAPL @ 270, one share in the archived account
    assert any("Archived account Old RRSP still holds value" in w for w in payload["warnings"])


def test_desktop_activity_amounts_are_signed_by_cash_direction(tracker):
    acct = holding(tracker.store)
    for kind, amount in [(TxnType.DEPOSIT, 1000), (TxnType.WITHDRAWAL, 50), (TxnType.FEE, 5), (TxnType.INTEREST, 2)]:
        tracker.store.add_transaction(Transaction(account_id=acct.saved_id, type=kind, amount=amount, currency="USD"))
    tracker.store.add_transaction(
        Transaction(account_id=acct.saved_id, type=TxnType.SPLIT, symbol="AAPL", ratio=2, currency="USD")
    )
    rows = {t["type"]: t for t in snapshot(tracker)["activity"]}
    signed = {k: (r["direction"], r["value"]) for k, r in rows.items()}
    assert signed == {
        "BUY": (-1, 300),
        "DEPOSIT": (1, 1000),
        "WITHDRAWAL": (-1, 50),
        "FEE": (-1, 5),
        "INTEREST": (1, 2),
        "SPLIT": (0, 0),
    }
    assert rows["SPLIT"]["ratio"] == 2
