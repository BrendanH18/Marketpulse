"""Persistence: schema v2 round-trips and legacy (v1) file migration."""
import json

from marketpulse.models import Portfolio
from marketpulse.storage import load_portfolio, save_portfolio


def test_round_trip_preserves_positions_transactions_and_currency(data_dir):
    p = Portfolio(name="rt", currency="CAD")
    p.buy("AAPL", 10, 100, fees=4.95, currency="USD", note="core")
    p.sell("AAPL", 4, 150)
    p.watchlist = ["SPY", "QQQ"]
    save_portfolio(p)

    loaded = load_portfolio("rt")
    assert loaded is not None
    assert loaded.currency == "CAD"
    assert loaded.watchlist == ["SPY", "QQQ"]
    pos = loaded.positions["AAPL"]
    assert pos.shares == 6
    assert pos.currency == "USD"
    assert pos.note == "core"
    assert len(loaded.transactions) == 2
    assert [t.action for t in loaded.transactions] == ["BUY", "SELL"]
    assert loaded.transactions[0].fees == 4.95
    assert loaded.realized_pnl() == p.realized_pnl()


def test_legacy_v1_file_migrates_with_synthesized_opening_buys(data_dir):
    legacy = {
        "name": "old",
        "currency": "CAD",
        "created_at": "2024-01-01T00:00:00",
        "watchlist": ["SPY"],
        "positions": {
            "XEQT.TO": {"ticker": "XEQT.TO", "shares": 100.0, "avg_cost": 28.5, "note": ""},
            "AAPL": {"ticker": "AAPL", "shares": 10.0, "avg_cost": 150.0, "note": "old note"},
        },
    }
    (data_dir / "old.json").write_text(json.dumps(legacy))

    p = load_portfolio("old")
    assert p is not None
    # positions preserved exactly
    assert p.positions["XEQT.TO"].shares == 100.0
    assert p.positions["AAPL"].avg_cost == 150.0
    assert p.positions["AAPL"].note == "old note"
    assert p.positions["AAPL"].currency == ""  # unknown until next buy
    # one opening BUY per position, replaying to the same holdings
    assert len(p.transactions) == 2
    by_ticker = {t.ticker: t for t in p.transactions}
    assert by_ticker["XEQT.TO"].action == "BUY"
    assert by_ticker["XEQT.TO"].shares == 100.0
    assert by_ticker["XEQT.TO"].price == 28.5
    assert by_ticker["XEQT.TO"].date == "2024-01-01T00:00:00"
    # opening balances carry no realized P&L
    assert p.realized_pnl() == {}


def test_migrated_ledger_persists_on_next_save(data_dir):
    legacy = {
        "name": "old2",
        "positions": {"SPY": {"ticker": "SPY", "shares": 5.0, "avg_cost": 400.0}},
    }
    (data_dir / "old2.json").write_text(json.dumps(legacy))

    p = load_portfolio("old2")
    save_portfolio(p)
    raw = json.loads((data_dir / "old2.json").read_text())
    assert raw["schema"] == 2
    assert len(raw["transactions"]) == 1
    assert raw["transactions"][0]["note"] == "opening balance (migrated)"


def test_atomic_save_leaves_no_tmp_file(data_dir):
    p = Portfolio(name="atomic")
    p.buy("SPY", 1, 400)
    save_portfolio(p)
    assert (data_dir / "atomic.json").exists()
    assert not list(data_dir.glob("*.tmp"))


def test_missing_portfolio_returns_none(data_dir):
    assert load_portfolio("nope") is None
