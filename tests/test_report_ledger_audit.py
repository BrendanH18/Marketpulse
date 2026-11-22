"""Verify the saved ledger audit sources with fictional accounts and entries."""

import pytest

from marketpulse.cli.base import App
from marketpulse.cli.report_ledger_audit import SOURCES, load_source
from marketpulse.models import Account, Transaction, TxnType


@pytest.fixture
def audit_app(tracker, monkeypatch, fake):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    monkeypatch.setattr(tracker.store, "ledger", lambda: pytest.fail("ledger audits should not replay transactions"))
    yield App()
    assert not fake.calls


def test_currency_audit_distinguishes_recorded_symbol_and_account_currencies(audit_app):
    store = audit_app.store
    visible = store.add_account(Account("Fictional CAD")).saved_id
    hidden = store.add_account(Account("Fictional Archived", currency="GBP", archived=True)).saved_id
    store.add_transactions(
        [
            Transaction(visible, TxnType.BUY, "2024-01-04", "FRUIT", 1, 20),
            Transaction(visible, TxnType.BUY, "2024-01-01", "FRUIT.TO", 1, 20, currency="USD"),
            Transaction(visible, TxnType.BUY, "2024-01-02", "FRUIT.L", 1, 20),
            Transaction(visible, TxnType.BUY, "2024-01-03", "FRUIT.TO", 1, 20),
            Transaction(visible, TxnType.DEPOSIT, "2024-01-05", amount=20),
            Transaction(hidden, TxnType.BUY, "2024-01-01", "ARCHIVED.L", 1, 20),
            Transaction(visible, TxnType.TRANSFER, "2024-01-06", "FRUIT.TO", 1, target_account_id=hidden),
        ]
    )
    changes = store._conn.total_changes
    name = "transaction-currency-audit"
    rows = load_source(name, audit_app)
    assert all(tuple(row) == SOURCES[name] for row in rows)
    assert [tuple(row.values()) for row in rows] == [
        (2, visible, "Fictional CAD", "2024-01-01", "BUY", "FRUIT.TO", "CAD", "USD", "USD", "explicit", True),
        (3, visible, "Fictional CAD", "2024-01-02", "BUY", "FRUIT.L", "CAD", None, "GBP", "symbol", True),
        (4, visible, "Fictional CAD", "2024-01-03", "BUY", "FRUIT.TO", "CAD", None, "CAD", "symbol", False),
        (1, visible, "Fictional CAD", "2024-01-04", "BUY", "FRUIT", "CAD", None, "CAD", "account", False),
        (5, visible, "Fictional CAD", "2024-01-05", "DEPOSIT", "", "CAD", None, "CAD", "account", False),
        (7, visible, "Fictional CAD", "2024-01-06", "TRANSFER", "FRUIT.TO", "CAD", None, "CAD", "symbol", False),
    ]
    assert store._conn.total_changes == changes


def test_transfer_routes_group_distinct_active_endpoints_in_each_direction(audit_app):
    store = audit_app.store
    cad = store.add_account(Account("Fictional CAD")).saved_id
    usd = store.add_account(Account("Fictional USD", currency="USD")).saved_id
    other_cad = store.add_account(Account("Fictional Other CAD")).saved_id
    archived = store.add_account(Account("Fictional Archived", archived=True)).saved_id
    removed = store.add_account(Account("Fictional Removed")).saved_id
    store.add_transactions(
        [
            Transaction(cad, TxnType.TRANSFER, "2024-01-08", "FRUIT.TO", 1, target_account_id=usd),
            Transaction(cad, TxnType.TRANSFER, "2024-01-06", "BERRY", 1, currency="USD", target_account_id=usd),
            Transaction(cad, TxnType.TRANSFER, "2024-01-07", "BERRY", 1, currency="USD", target_account_id=usd),
            Transaction(usd, TxnType.TRANSFER, "2024-01-09", "FRUIT.TO", 1, target_account_id=cad),
            Transaction(cad, TxnType.TRANSFER, "2024-01-10", "FRUIT.TO", 1, target_account_id=other_cad),
            Transaction(cad, TxnType.TRANSFER, "2024-01-11", "A.TO", 1, target_account_id=archived),
            Transaction(archived, TxnType.TRANSFER, "2024-01-12", "B.TO", 1, target_account_id=cad),
            Transaction(cad, TxnType.TRANSFER, "2024-01-13", "C.TO", 1, target_account_id=removed),
        ]
    )
    store.delete_account(removed)
    changes = store._conn.total_changes
    name = "transfer-routes"
    rows = load_source(name, audit_app)
    assert all(tuple(row) == SOURCES[name] for row in rows)
    assert [tuple(row.values()) for row in rows] == [
        (
            cad,
            "Fictional CAD",
            usd,
            "Fictional USD",
            3,
            "2024-01-06",
            "2024-01-08",
            ["CAD", "USD"],
            ["BERRY", "FRUIT.TO"],
            False,
        ),
        (
            cad,
            "Fictional CAD",
            other_cad,
            "Fictional Other CAD",
            1,
            "2024-01-10",
            "2024-01-10",
            ["CAD"],
            ["FRUIT.TO"],
            True,
        ),
        (usd, "Fictional USD", cad, "Fictional CAD", 1, "2024-01-09", "2024-01-09", ["CAD"], ["FRUIT.TO"], False),
    ]
    assert store._conn.total_changes == changes


@pytest.mark.parametrize("source", SOURCES)
def test_ledger_audits_have_no_rows_without_transactions(source, audit_app):
    audit_app.store.add_account(Account("Fictional Empty"))
    assert load_source(source, audit_app) == []
