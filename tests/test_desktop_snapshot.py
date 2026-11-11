"""Snapshot work may be reused, but bridge rows and edit/Tax revisions must stay identical."""

import hashlib
import json
from dataclasses import asdict, replace
from datetime import date

import pytest

from marketpulse import desktop, models
from marketpulse.models import Account, Transaction, TxnType


def test_snapshot_preserves_saved_watch_order_when_quotes_are_missing(tracker):
    symbols = ["QA-UNPRICED", "AAPL", "QA-MISSING"]
    tracker.store.remove_watch(tracker.store.watchlist())
    tracker.store.add_watch(symbols)
    payload = desktop.snapshot(tracker)
    assert payload["watchlist_symbols"] == symbols
    assert "QA-UNPRICED" not in {row["symbol"] for row in payload["status"]["watchlist"]}
    tracker.store.move_watch("QA-MISSING", -2)
    assert desktop.snapshot(tracker)["watchlist_symbols"] == ["QA-MISSING", "QA-UNPRICED", "AAPL"]


def legacy_revision(record, generation):
    fields = json.dumps({**asdict(record), "generation": generation}, sort_keys=True, default=str)
    return hashlib.sha256(fields.encode()).hexdigest()[:16]


@pytest.mark.parametrize("kind", list(TxnType))
@pytest.mark.parametrize("generation", ["", "restored-fictional-ledger"])
def test_activity_and_transaction_revisions_preserve_the_original_fields(kind, generation):
    txn = Transaction(
        account_id=1,
        id=42,
        type=kind,
        date="2025-01-02",
        symbol="XEQT.TO",
        quantity=1.25,
        price=32.5,
        amount=7.5,
        fees=0.25,
        currency="CAD",
        note="Fictional épargne 🪴",
        ratio=2.0,
        target_account_id=2,
    )
    accounts = {2: Account(name="Fictional destination", id=2)}
    expected = {
        **asdict(txn),
        "value": txn.gross_value,
        "direction": txn.cash_direction,
        "target_account": accounts[2].name,
        "revision": legacy_revision(txn, generation),
    }
    assert desktop.activity_row(txn, accounts, generation) == expected
    assert txn.revision(generation) == expected["revision"]


def test_snapshot_reuses_rows_and_keeps_archived_transactions_in_ledger_revision(tracker, monkeypatch):
    store = tracker.store
    active = store.add_account(Account(name="Fictional active"))
    old = store.add_account(Account(name="Fictional archived", archived=True))
    for account in (active, old):
        store.add_transaction(Transaction(account_id=account.saved_id, type=TxnType.FEE, date="2025-01-02", amount=5))
    generation = store.restore_id
    txns = store.transactions()
    parts = [
        date.today().isoformat(),
        *(legacy_revision(t, generation) for t in txns),
        *(legacy_revision(a, generation) for a in store.accounts(include_archived=True)),
        json.dumps(sorted(store.rooms().items())),
        tracker.base,
        repr(tracker.config.capital_gains_inclusion),
    ]
    expected = hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]
    reads = []
    serializations = []
    transactions = store.transactions
    original_asdict = asdict
    run_cycle = desktop.run_cycle

    def read_transactions(*args, **kwargs):
        reads.append(True)
        return transactions(*args, **kwargs)

    def serialize(record):
        if isinstance(record, Transaction):
            serializations.append(record.saved_id)
        return original_asdict(record)

    def cycle_then_count(*args, **kwargs):
        cycle = run_cycle(*args, **kwargs)
        monkeypatch.setattr(store, "transactions", read_transactions)
        return cycle

    monkeypatch.setattr(desktop, "run_cycle", cycle_then_count)
    monkeypatch.setattr(desktop, "asdict", serialize)
    monkeypatch.setattr(models, "asdict", serialize)
    payload = desktop.snapshot(tracker)
    assert payload["ledger_revision"] == expected
    assert [t["id"] for t in payload["activity"]] == [txns[0].saved_id]
    assert payload["activity"][0]["revision"] == legacy_revision(txns[0], generation)
    # One shared read for snapshot rows/replay, plus the unchanged contribution-room read.
    assert len(reads) == 2
    assert sorted(serializations) == [t.saved_id for t in txns]

    # A second refresh must not reuse an old row or hash, even for hidden transactions.
    store.update_transaction(replace(txns[1], amount=6))
    assert desktop.snapshot(tracker)["ledger_revision"] != expected
