"""Fictional saved data proves the offline portfolio report sources."""

from __future__ import annotations

import json

import pytest

from marketpulse.cli.base import App
from marketpulse.cli.report_portfolio import SOURCES, load_source
from marketpulse.db import Snapshot
from marketpulse.models import Account, Alert, Asset, Quote, Transaction, TxnType


@pytest.fixture
def report_app(tracker):
    store = tracker.store
    active = store.add_account(Account("Fictional Cash", track_cash=True))
    archived = store.add_account(Account("Archived Fictional", track_cash=True, archived=True))
    untracked = store.add_account(Account("Fictional Invested"))
    for account in (active, archived, untracked):
        for txn in (
            Transaction(account.saved_id, TxnType.DEPOSIT, "2024-01-01", amount=1000, currency="CAD"),
            Transaction(account.saved_id, TxnType.BUY, "2024-01-02", "FIC.TO", 10, 20, currency="CAD"),
            Transaction(account.saved_id, TxnType.SELL, "2024-01-03", "FIC.TO", 2, 25, currency="CAD"),
            Transaction(account.saved_id, TxnType.DIVIDEND, "2024-01-04", "FIC.TO", amount=8, currency="CAD"),
        ):
            store.add_transaction(txn)
    store.upsert_asset(Asset("FIC.TO", name="Fictional Fund", currency="CAD"))
    store.upsert_snapshot(Snapshot("2024-01-03", 1100, 1000, 1000, "CAD", {}))
    store.upsert_snapshot(Snapshot("2024-01-04", 1200, 1000, 1000, "CAD", {}))
    store.cache_quotes([Quote("FIC.TO", 25, 24, name="Fictional Fund", currency="CAD", fetched_at=1700000000)])
    store.add_alert(Alert("FIC.TO", "above", 30, note="fictional alert"))
    store.add_watch(["FIC.TO", "FIC-B.TO"])
    store.set_targets({"equity": 75, "cash": 25})
    store.backup()
    app = App()
    app._tracker = tracker
    return app


@pytest.mark.parametrize("name", SOURCES)
def test_sources_have_stable_schemas_without_network_or_writes(name, report_app, fake):
    store = report_app.store
    changes = store._conn.total_changes
    snapshots = store.snapshots()
    backups = store.backups()
    rows = load_source(name, report_app)
    assert rows
    assert all(tuple(row) == SOURCES[name] for row in rows)
    assert json.loads(json.dumps(rows))
    assert not fake.calls
    assert store._conn.total_changes == changes
    assert store.snapshots() == snapshots
    assert store.backups() == backups


@pytest.mark.parametrize("name", ["accounts", "transactions", "positions", "cash", "realized", "payouts"])
def test_sources_hide_archived_accounts(name, report_app):
    rows = load_source(name, report_app)
    assert "Archived Fictional" not in json.dumps(rows)
    archived = report_app.store.get_account("Archived Fictional")
    assert archived is not None
    assert all(row.get("account_id", row.get("id")) != archived.id for row in rows)


def test_sources_reuse_recorded_values_in_native_currency(report_app):
    assert load_source("positions", report_app)[0] == {
        "account_id": 1,
        "account": "Fictional Cash",
        "symbol": "FIC.TO",
        "quantity": 8,
        "book": 160,
        "average_cost": 20,
        "currency": "CAD",
        "first_date": "2024-01-02",
    }
    assert load_source("cash", report_app) == [
        {"account_id": 1, "account": "Fictional Cash", "currency": "CAD", "balance": 858}
    ]
    assert load_source("snapshots", report_app)[1]["change"] == 100
    assert all(row["gain"] == 10 for row in load_source("realized", report_app))
    assert all(row["amount"] == 8 for row in load_source("payouts", report_app))
    assert load_source("watchlist", report_app) == [
        {"position": 1, "symbol": "FIC.TO"},
        {"position": 2, "symbol": "FIC-B.TO"},
    ]
    assert load_source("cached-quotes", report_app)[0]["stale"] is True


def test_transfer_to_archived_account_hides_destination(report_app):
    archived = report_app.store.get_account("Archived Fictional")
    assert archived is not None
    report_app.store.add_transaction(
        Transaction(1, TxnType.TRANSFER, "2024-01-05", "FIC.TO", 1, target_account_id=archived.id)
    )
    row = load_source("transactions", report_app)[-1]
    assert row["type"] == "TRANSFER"
    assert row["target_account_id"] is None


@pytest.mark.parametrize("name", SOURCES)
def test_empty_saved_data_returns_empty_rows(name, tracker):
    app = App()
    app._tracker = tracker
    assert load_source(name, app) == []


def test_unknown_source_is_rejected_before_opening_tracker(monkeypatch):
    app = App()
    monkeypatch.setattr(App, "store", property(lambda self: pytest.fail("must not open store")))
    with pytest.raises(KeyError, match="unknown"):
        load_source("unknown", app)
