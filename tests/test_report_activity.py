"""Verify the offline report calendar and symbol histories with a fictional ledger."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.cli.base import App
from marketpulse.cli.report_activity import SOURCES, load_source
from marketpulse.db import Store
from marketpulse.models import Account, Transaction, TxnType


@pytest.fixture
def activity_app(tracker, monkeypatch):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    store = tracker.store
    first = store.add_account(Account("Fictional First")).saved_id
    second = store.add_account(Account("Fictional Second")).saved_id
    archived = store.add_account(Account("Fictional Hidden", archived=True)).saved_id
    store.add_account(Account("Fictional Empty"))
    store.add_transactions(
        [
            Transaction(second, TxnType.DIVIDEND, "2024-02-29", "FRUIT.TO", amount=2),
            Transaction(first, TxnType.DEPOSIT, "2024-01-02", amount=100),
            Transaction(first, TxnType.BUY, "2024-01-08", "FRUIT.TO", 2, 10),
            Transaction(first, TxnType.BUY, "2024-01-21", "FRUIT.TO", 1, 10),
            Transaction(first, TxnType.TRANSFER, "2024-01-23", "FRUIT.TO", 1, target_account_id=second),
            Transaction(first, TxnType.TRANSFER, "2024-01-24", "FRUIT.TO", 1, target_account_id=archived),
            Transaction(first, TxnType.WITHDRAWAL, "2024-02-01", amount=15),
            Transaction(archived, TxnType.BUY, "2024-02-19", "HIDDEN.TO", 2, 10),
            Transaction(archived, TxnType.TRANSFER, "2024-02-20", "HIDDEN.TO", 1, target_account_id=second),
            Transaction(second, TxnType.SELL, "2024-03-01", "FRUIT.TO", 1, 20),
        ]
    )
    return App()


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "transaction-months",
            [
                (1, "Fictional First", "2024-01", "2024-01-02", "2024-01-24", 5, ["BUY", "DEPOSIT", "TRANSFER"], 1),
                (1, "Fictional First", "2024-02", "2024-02-01", "2024-02-01", 1, ["WITHDRAWAL"], 0),
                (2, "Fictional Second", "2024-01", "2024-01-23", "2024-01-23", 1, ["TRANSFER"], 1),
                (2, "Fictional Second", "2024-02", "2024-02-29", "2024-02-29", 1, ["DIVIDEND"], 1),
                (2, "Fictional Second", "2024-03", "2024-03-01", "2024-03-01", 1, ["SELL"], 1),
            ],
        ),
        (
            "account-symbols",
            [
                (1, "Fictional First", "FRUIT.TO", "2024-01-08", "2024-01-24", 4, ["BUY", "TRANSFER"]),
                (2, "Fictional Second", "FRUIT.TO", "2024-01-23", "2024-03-01", 3, ["DIVIDEND", "SELL", "TRANSFER"]),
            ],
        ),
    ],
)
def test_activity_reports_without_replay_or_writes(source, expected, activity_app, fake, monkeypatch):
    store = activity_app.store
    changes = store._conn.total_changes
    monkeypatch.setattr(store, "ledger", lambda: pytest.fail("activity reports should not replay the ledger"))
    result = CliRunner().invoke(main, ["report", source])
    assert result.exit_code == 0, result.output
    rows = json.loads(result.output)
    assert rows == [dict(zip(SOURCES[source], values, strict=True)) for values in expected]
    assert all(tuple(row) == SOURCES[source] for row in rows)
    assert not fake.calls
    assert store._conn.total_changes == changes


@pytest.mark.parametrize("source", SOURCES)
def test_activity_reports_empty_ledger(source, tracker, monkeypatch):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    assert load_source(source, App()) == []


def test_activity_report_uses_one_ledger_snapshot(activity_app, monkeypatch):
    store = activity_app.store
    read_accounts = store.accounts
    accounts = read_accounts()
    replaced = accounts[0]
    other = Store(store.path)

    def interleave():
        old_accounts = read_accounts()
        # Simulate a restore replacing an active account with an archived one sharing its ID.
        with other.transaction():
            other.update_account(replace(replaced, name="Fictional Replacement", archived=True))
            other.add_transaction(Transaction(replaced.saved_id, TxnType.BUY, "2024-03-01", "SECRET.TO", 1, 10))
        return old_accounts

    try:
        with monkeypatch.context() as patch:
            patch.setattr(store, "accounts", interleave)
            rows = load_source("account-symbols", activity_app)
    finally:
        other.close()
    assert [(row["account"], row["symbol"]) for row in rows] == [
        ("Fictional First", "FRUIT.TO"),
        ("Fictional Second", "FRUIT.TO"),
    ]
    assert [row["account"] for row in load_source("account-symbols", activity_app)] == ["Fictional Second"]
