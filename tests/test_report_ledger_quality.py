"""Verify the duplicate-transaction and asset-usage sources with fictional accounts and entries."""

import json

import pytest
from click.testing import CliRunner

from marketpulse.cli import main
from marketpulse.cli.base import App
from marketpulse.cli.report_ledger_quality import PRESETS, SOURCES, load_source
from marketpulse.models import Account, Alert, Asset, AssetKind, Transaction, TxnType


@pytest.fixture
def quality_app(tracker, monkeypatch, fake):
    monkeypatch.setattr(App, "tracker", property(lambda self: tracker))
    yield App()
    assert not fake.calls


def seed_duplicates(store):
    cad = store.add_account(Account("Fictional CAD")).saved_id
    usd = store.add_account(Account("Fictional USD", currency="USD")).saved_id
    archived = store.add_account(Account("Fictional Archived", archived=True)).saved_id
    store.add_transactions(
        [
            # 1-3: the same buy three times; an explicit CAD matches the CAD implied by .TO, and the notes
            # differ only in surrounding spaces.
            Transaction(cad, TxnType.BUY, "2024-02-01", "FRUIT.TO", 10, 5, note="first"),
            Transaction(cad, TxnType.BUY, "2024-02-01", "FRUIT.TO", 10, 5, note=" first "),
            Transaction(cad, TxnType.BUY, "2024-02-01", "FRUIT.TO", 10, 5, currency="CAD", note="first"),
            # 4: one more field differs, so it stands alone.
            Transaction(cad, TxnType.BUY, "2024-02-01", "FRUIT.TO", 10, 5, fees=1),
            # 5-6: cash entries with different notes.
            Transaction(cad, TxnType.DEPOSIT, "2024-01-15", amount=100, note="paycheque"),
            Transaction(cad, TxnType.DEPOSIT, "2024-01-15", amount=100, note="paycheck"),
            # 7-8: a transfer recorded twice into an active account.
            Transaction(cad, TxnType.TRANSFER, "2024-03-01", "FRUIT.TO", 2, target_account_id=usd),
            Transaction(cad, TxnType.TRANSFER, "2024-03-01", "FRUIT.TO", 2, target_account_id=usd),
            # 9-10: duplicates only in an archived account stay hidden.
            Transaction(archived, TxnType.BUY, "2024-01-01", "HIDDEN.TO", 1, 1),
            Transaction(archived, TxnType.BUY, "2024-01-01", "HIDDEN.TO", 1, 1),
            # 11-12: a transfer recorded twice into an archived account keeps its target id but not its name.
            Transaction(cad, TxnType.TRANSFER, "2024-03-02", "FRUIT.TO", 1, target_account_id=archived),
            Transaction(cad, TxnType.TRANSFER, "2024-03-02", "FRUIT.TO", 1, target_account_id=archived),
            # 13-15: the same sell in two effective currencies is two different entries.
            Transaction(usd, TxnType.SELL, "2024-03-05", "FRUIT.TO", 1, 5, currency="USD"),
            Transaction(usd, TxnType.SELL, "2024-03-05", "FRUIT.TO", 1, 5, currency="USD"),
            Transaction(usd, TxnType.SELL, "2024-03-05", "FRUIT.TO", 1, 5),
            # 16-17: an earlier account on the same day sorts first.
            Transaction(cad, TxnType.DIVIDEND, "2024-03-05", "FRUIT.TO", amount=3),
            Transaction(cad, TxnType.DIVIDEND, "2024-03-05", "FRUIT.TO", amount=3),
            # 18-19: splits with different ratios are not duplicates.
            Transaction(cad, TxnType.SPLIT, "2024-04-01", "FRUIT.TO", ratio=2),
            Transaction(cad, TxnType.SPLIT, "2024-04-01", "FRUIT.TO", ratio=3),
            # 20-22: three sells, then a fourth with a different date.
            Transaction(cad, TxnType.SELL, "2024-04-02", "FRUIT.TO", 1, 6, note="a"),
            Transaction(cad, TxnType.SELL, "2024-04-02", "FRUIT.TO", 1, 6, note="b"),
            Transaction(cad, TxnType.SELL, "2024-04-02", "FRUIT.TO", 1, 6, note="a"),
            Transaction(cad, TxnType.SELL, "2024-04-03", "FRUIT.TO", 1, 6, note="a"),
        ]
    )
    return cad, usd, archived


def seed_usage(store):
    cad = store.add_account(Account("Fictional CAD")).saved_id
    usd = store.add_account(Account("Fictional USD", currency="USD")).saved_id
    archived = store.add_account(Account("Fictional Archived", archived=True)).saved_id
    store.upsert_asset(Asset("HELDCO", name="Fictional Held Co"))
    store.upsert_asset(Asset("HOUSE", kind=AssetKind.MANUAL, name="  "))
    store.upsert_asset(Asset("IDLE", name="Fictional Idle"))
    store.add_transactions(
        [
            # Held across two active accounts after a transfer between them.
            Transaction(cad, TxnType.BUY, "2024-01-02", "HELDCO", 10, 1),
            Transaction(cad, TxnType.SELL, "2024-02-02", "HELDCO", 4, 1),
            Transaction(cad, TxnType.TRANSFER, "2024-03-02", "HELDCO", 3, target_account_id=usd),
            # Bought and sold out.
            Transaction(usd, TxnType.BUY, "2024-01-05", "GONE", 1, 1),
            Transaction(usd, TxnType.SELL, "2024-01-06", "GONE", 1, 1),
            # Float noise left after selling everything is not a holding.
            Transaction(cad, TxnType.BUY, "2024-01-07", "NOISE", 0.1, 1),
            Transaction(cad, TxnType.BUY, "2024-01-08", "NOISE", 0.2, 1),
            Transaction(cad, TxnType.SELL, "2024-01-09", "NOISE", 0.3, 1),
            # A symbol only an archived account uses is hidden.
            Transaction(archived, TxnType.BUY, "2024-01-01", "SECRET", 5, 1),
            # A position moved in from an archived account is held, without a visible transaction.
            Transaction(archived, TxnType.BUY, "2024-01-01", "MOVED", 5, 1),
            Transaction(archived, TxnType.TRANSFER, "2024-01-03", "MOVED", 5, target_account_id=usd),
            # Cash entries have no symbol.
            Transaction(cad, TxnType.DEPOSIT, "2024-01-01", amount=50),
        ]
    )
    store.add_watch(["watchme", "heldco"])
    store.add_alert(Alert("alertonly", "above", 10))
    store.add_alert(Alert("watchme", "below", 1, active=False))
    store.add_alert(Alert("heldco", "above", 20))
    store.add_alert(Alert("heldco", "below", 2))
    return cad, usd, archived


def test_duplicate_transactions_group_every_field_but_the_note(quality_app):
    store = quality_app.store
    cad, usd, archived = seed_duplicates(store)
    changes = store._conn.total_changes
    name = "duplicate-transactions"
    rows = load_source(name, quality_app)
    assert all(tuple(row) == SOURCES[name] for row in rows)
    cad_name, usd_name, fruit = "Fictional CAD", "Fictional USD", "FRUIT.TO"
    assert [tuple(row.values()) for row in rows] == [
        (2, [5, 6], cad, cad_name, "2024-01-15", "DEPOSIT", "", 0.0, 0.0, 100.0, 0.0, "CAD", None, None, True),
        (3, [1, 2, 3], cad, cad_name, "2024-02-01", "BUY", fruit, 10.0, 5.0, 0.0, 0.0, "CAD", None, None, False),
        (2, [7, 8], cad, cad_name, "2024-03-01", "TRANSFER", fruit, 2.0, 0.0, 0.0, 0.0, "CAD", usd, usd_name, False),
        (2, [11, 12], cad, cad_name, "2024-03-02", "TRANSFER", fruit, 1.0, 0.0, 0.0, 0.0, "CAD", archived, None, False),
        (2, [16, 17], cad, cad_name, "2024-03-05", "DIVIDEND", fruit, 0.0, 0.0, 3.0, 0.0, "CAD", None, None, False),
        (2, [13, 14], usd, usd_name, "2024-03-05", "SELL", fruit, 1.0, 5.0, 0.0, 0.0, "USD", None, None, False),
        (3, [20, 21, 22], cad, cad_name, "2024-04-02", "SELL", fruit, 1.0, 6.0, 0.0, 0.0, "CAD", None, None, True),
    ]
    assert store._conn.total_changes == changes


def test_asset_usage_classifies_saved_and_referenced_symbols(quality_app):
    store = quality_app.store
    seed_usage(store)
    changes = store._conn.total_changes
    name = "asset-usage"
    rows = load_source(name, quality_app)
    assert all(tuple(row) == SOURCES[name] for row in rows)
    both = ["Fictional CAD", "Fictional USD"]
    assert [tuple(row.values()) for row in rows] == [
        ("ALERTONLY", "watched", False, None, None, 0, [], 0.0, False, 1, None, None),
        ("GONE", "traded", False, None, None, 2, ["Fictional USD"], 0.0, False, 0, "2024-01-05", "2024-01-06"),
        ("HELDCO", "held", True, "market", "Fictional Held Co", 3, both, 6.0, True, 2, "2024-01-02", "2024-03-02"),
        ("HOUSE", "unused", True, "manual", None, 0, [], 0.0, False, 0, None, None),
        ("IDLE", "unused", True, "market", "Fictional Idle", 0, [], 0.0, False, 0, None, None),
        ("MOVED", "held", False, None, None, 0, ["Fictional USD"], 5.0, False, 0, None, None),
        ("NOISE", "traded", False, None, None, 3, ["Fictional CAD"], 0.0, False, 0, "2024-01-07", "2024-01-09"),
        ("WATCHME", "watched", False, None, None, 0, [], 0.0, True, 1, None, None),
    ]
    assert store._conn.total_changes == changes


@pytest.mark.parametrize("source", SOURCES)
def test_ledger_quality_has_no_rows_without_saved_data(source, quality_app):
    quality_app.store.add_account(Account("Fictional Empty"))
    assert load_source(source, quality_app) == []


def report(*arguments):
    result = CliRunner().invoke(main, list(arguments))
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


@pytest.mark.parametrize(
    ("preset", "expected"),
    [
        ("same-note", [[1, 2, 3], [7, 8], [11, 12], [16, 17], [13, 14]]),
        ("trades", [[1, 2, 3], [13, 14], [20, 21, 22]]),
        ("repeated", [[1, 2, 3], [20, 21, 22]]),
    ],
)
def test_duplicate_transaction_presets(preset, expected, quality_app):
    seed_duplicates(quality_app.store)
    source = "duplicate-transactions"
    rows = report("report", source, "--preset", preset, "--fields", "transaction_ids")
    assert [row["transaction_ids"] for row in rows] == expected
    metrics = ("--metric", "groups=count", "--metric", "entries=number-sum:transactions")
    summary = report("summarize", source, "--preset", preset, *metrics)
    assert summary == [{"groups": len(expected), "entries": str(sum(map(len, expected)))}]  # sums are exact text


@pytest.mark.parametrize(
    ("preset", "usage", "expected"),
    [
        ("held", "held", ["HELDCO", "MOVED"]),
        ("watch-only", "watched", ["ALERTONLY", "WATCHME"]),
        ("unused", "unused", ["HOUSE", "IDLE"]),
    ],
)
def test_asset_usage_presets(preset, usage, expected, quality_app):
    seed_usage(quality_app.store)
    source = "asset-usage"
    rows = report("report", source, "--preset", preset, "--fields", "symbol")
    assert [row["symbol"] for row in rows] == expected
    summary = report("summarize", source, "--preset", preset, "--metric", "symbols=count", "--group-by", "usage")
    assert summary == [{"usage": usage, "symbols": len(expected)}]


def test_every_preset_is_tested():
    assert {source: set(presets) for source, presets in PRESETS.items()} == {
        "duplicate-transactions": {"same-note", "trades", "repeated"},
        "asset-usage": {"held", "watch-only", "unused"},
    }
