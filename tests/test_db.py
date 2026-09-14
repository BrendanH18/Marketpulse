import json
import time

import pytest

from marketpulse.config import DEFAULT_WATCHLIST
from marketpulse.db import Snapshot, Store, migrate_legacy_json
from marketpulse.models import Account, AccountType, Alert, Asset, AssetClass, AssetKind, Quote, Transaction, TxnType


def test_accounts_crud_and_lookup(store):
    tfsa = store.add_account(Account(name="Questrade TFSA", type=AccountType.TFSA))
    store.add_account(Account(name="Margin", type=AccountType.MARGIN))
    assert store.get_account("questrade tfsa").id == tfsa.id
    assert store.get_account(str(tfsa.id)).name == "Questrade TFSA"
    assert store.get_account("tfsa").id == tfsa.id  # unique type match
    assert store.get_account("nope") is None
    with pytest.raises(ValueError, match="already exists"):
        store.add_account(Account(name="questrade TFSA"))
    tfsa.archived = True
    store.update_account(tfsa)
    assert [a.name for a in store.accounts()] == ["Margin"]
    assert len(store.accounts(include_archived=True)) == 2


def test_transactions_roundtrip_and_cascade(store):
    acct = store.add_account(Account(name="Main"))
    t = store.add_transaction(
        Transaction(account_id=acct.id, type=TxnType.BUY, date="yesterday", symbol="aapl", quantity=2, price=10)
    )
    assert t.id and len(t.date) == 10
    t.quantity = 3
    store.update_transaction(t)
    assert store.transactions()[0].quantity == 3
    with pytest.raises(ValueError):
        store.add_transaction(Transaction(account_id=acct.id, type=TxnType.BUY, symbol="X", quantity=-1, price=1))
    store.delete_account(acct.id)
    assert store.transactions() == []


def test_watchlist_order(store):
    assert store.add_watch(["b", "a", "B"]) == ["B", "A"]
    store.add_watch(["C"])
    store.move_watch("C", -2)
    assert store.watchlist() == ["C", "B", "A"]
    assert store.remove_watch(["B", "Z"]) == ["B"]


def test_alerts_assets_room_targets_snapshots(store):
    a = store.add_alert(Alert("AAPL", "above", 100, note="breakout"))
    a.triggered_at = "2026-01-01T00:00:00"
    store.update_alert(a)
    assert store.alerts(active_only=True)[0].triggered_at
    store.upsert_asset(
        Asset(
            "GIC", kind=AssetKind.FIXED_INCOME, rate=4.5, asset_class=AssetClass.FIXED_INCOME, start_date="2026-01-01"
        )
    )
    assert store.assets()["GIC"].rate == 4.5
    store.set_room("tfsa", 2026, 7000)
    assert store.rooms() == {"TFSA": (2026, 7000)}
    store.set_targets({"etf": 90, "cash": 10})
    assert store.targets() == {"cash": 10, "etf": 90}
    store.upsert_snapshot(Snapshot("2026-01-01", 10, 9, 9, "CAD", {"x": 1}))
    store.upsert_snapshot(Snapshot("2026-01-01", 11, 9, 9, "CAD", {}))
    assert [s.net_worth for s in store.snapshots()] == [11]


def test_quote_cache_marks_stale(store):
    store.cache_quotes([Quote(symbol="AAPL", price=1, prev_close=1, intraday=[1.0, 2.0], fetched_at=time.time())])
    cached = store.cached_quotes(["AAPL", "MSFT"])
    assert list(cached) == ["AAPL"] and cached["AAPL"].stale and cached["AAPL"].intraday == [1.0, 2.0]


def _write(path, data):
    path.write_text(json.dumps(data))


def test_migrates_schema2_json_and_reconciles_removed_positions(tmp_path):
    folder = tmp_path / "legacy"
    folder.mkdir()
    _write(
        folder / "default.json",
        {
            "schema": 2,
            "name": "default",
            "currency": "CAD",
            "created_at": "2024-01-01T00:00:00",
            "watchlist": ["qqq"],
            "positions": {"AAPL": {"ticker": "AAPL", "shares": 10, "avg_cost": 150, "currency": ""}},
            "transactions": [
                {
                    "ticker": "AAPL",
                    "action": "BUY",
                    "shares": 10,
                    "price": 150,
                    "date": "2024-01-02",
                    "fees": 0,
                    "currency": "",
                },
                {
                    "ticker": "MSFT",
                    "action": "BUY",
                    "shares": 2,
                    "price": 300,
                    "date": "2024-01-03",
                    "fees": 0,
                    "currency": "USD",
                },
            ],
        },
    )
    store = Store(folder / "marketpulse.db")
    assert migrate_legacy_json(store, folder) == ["default.json"]
    assert store.accounts()[0].name == "Main"
    state = store.ledger()
    held = {h.symbol: h for h in state.open_holdings()}
    assert set(held) == {"AAPL"}
    assert held["AAPL"].currency == "USD"
    assert [r.gain for r in state.realized if r.symbol == "MSFT"] == [pytest.approx(0)]
    assert store.watchlist() == ["QQQ"]
    assert migrate_legacy_json(store, folder) == []  # runs once
    assert len(store.accounts()) == 1


def test_migrates_schema1_positions(tmp_path):
    _write(
        tmp_path / "rrsp.json",
        {
            "name": "rrsp",
            "currency": "CAD",
            "created_at": "2023-05-01T09:00:00",
            "positions": {"VFV.TO": {"ticker": "VFV.TO", "shares": 5, "avg_cost": 100}},
        },
    )
    store = Store(tmp_path / "db.sqlite")
    migrate_legacy_json(store, tmp_path)
    h = store.ledger().open_holdings()[0]
    assert (h.symbol, h.quantity, h.avg_cost, h.currency, h.first_date) == ("VFV.TO", 5, 100, "CAD", "2023-05-01")


def test_fresh_install_seeds_watchlist():
    store = Store.open_default()
    assert store.watchlist() == DEFAULT_WATCHLIST
    assert store.ensure_default_account().name == "Main"
