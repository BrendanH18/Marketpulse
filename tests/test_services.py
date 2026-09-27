from datetime import date, timedelta

import pytest

from marketpulse.db import Snapshot
from marketpulse.ledger import replay
from marketpulse.models import Account, AccountType, Alert, Asset, AssetKind, FxRates, Quote, Transaction, TxnType
from marketpulse.valuation import build_view


def test_valuation_prices_every_asset_kind(tracker, store):
    main = store.add_account(Account(name="Main"))
    tfsa = store.add_account(Account(name="TFSA", type=AccountType.TFSA, track_cash=True))
    store.add_transaction(
        Transaction(
            account_id=main.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="AAPL",
            quantity=10,
            price=100,
            currency="USD",
        )
    )
    store.add_transaction(
        Transaction(account_id=tfsa.id, type=TxnType.DEPOSIT, date="2024-01-01", amount=1000, currency="CAD")
    )
    store.add_transaction(
        Transaction(
            account_id=tfsa.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="XEQT.TO",
            quantity=10,
            price=30,
            currency="CAD",
        )
    )
    store.upsert_asset(
        Asset(
            "GIC1",
            kind=AssetKind.FIXED_INCOME,
            rate=0,
            start_date="2024-01-01",
            maturity_date="2030-01-01",
            currency="CAD",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=main.id,
            type=TxnType.BUY,
            date="2024-01-01",
            symbol="GIC1",
            quantity=1,
            price=500,
            currency="CAD",
        )
    )
    store.upsert_asset(Asset("HOUSE", kind=AssetKind.MANUAL, currency="CAD"))
    store.add_transaction(
        Transaction(
            account_id=main.id,
            type=TxnType.BUY,
            date="2020-01-01",
            symbol="HOUSE",
            quantity=1,
            price=1000,
            currency="CAD",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=main.id, type=TxnType.VALUATION, date="2024-06-01", symbol="HOUSE", price=1500, currency="CAD"
        )
    )

    view = tracker.valuation()
    # AAPL 10×200×1.35 + XEQT 10×40 + TFSA cash 700 + GIC 500 + HOUSE 1500
    assert view.net_worth == pytest.approx(2700 + 400 + 700 + 500 + 1500)
    assert view.cash_total == pytest.approx(700)
    assert view.day_change == pytest.approx(10 * 10 * 1.35 - 5)
    assert not view.excluded
    classes = {b.key: b.value for b in view.by_class}
    assert classes["fixed_income"] == pytest.approx(500)
    assert classes["alternative"] == pytest.approx(1500)
    assert classes["cash"] == pytest.approx(700)
    assert sum(b.weight for b in view.by_class) == pytest.approx(100)
    assert len(store.snapshots()) == 1  # today's snapshot recorded


def test_ledger_currency_mismatch_is_converted(tracker, store):
    acct = store.add_account(Account(name="Main"))
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="AAPL",
            quantity=1,
            price=250,
            currency="CAD",
        )
    )
    view = tracker.valuation()
    assert view.positions[0].price == pytest.approx(270)


def test_missing_fx_excludes_position(tracker, store, fake):
    fake.set_quote("SAP.DE", 100, 100, "EUR")
    acct = store.add_account(Account(name="Main"))
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="SAP.DE",
            quantity=1,
            price=90,
            currency="EUR",
        )
    )
    view = tracker.valuation()
    assert view.excluded == ["SAP.DE"] and view.net_worth == 0
    assert store.snapshots() == []  # incomplete valuations never become history


def test_add_transaction_uses_listing_currency_and_blocks_oversell(tracker, store):
    acct = store.add_account(Account(name="Main"))
    t = tracker.add_transaction(Transaction(account_id=acct.id, type=TxnType.BUY, symbol="AAPL", quantity=1, price=200))
    assert t.currency == "USD"
    with pytest.raises(ValueError, match="only 1 held"):
        tracker.add_transaction(
            Transaction(account_id=acct.id, type=TxnType.SELL, symbol="AAPL", quantity=2, price=200)
        )


def test_status_payload_titles(tracker, store):
    acct = store.add_account(Account(name="Main", type=AccountType.TFSA))
    tracker.add_transaction(
        Transaction(account_id=acct.id, type=TxnType.BUY, date="2024-01-01", symbol="AAPL", quantity=1, price=100)
    )
    store.add_watch(["XEQT.TO"])
    payload = tracker.status_payload()
    assert payload["title"].startswith("▲")
    assert payload["accounts"][0]["type"] == "TFSA"
    acct.archived = True
    store.update_account(acct)
    assert tracker.status_payload()["accounts"][0]["type"] == "TFSA"  # archived accounts keep their type
    assert payload["watchlist"][0]["symbol"] == "XEQT.TO"
    assert payload["theme"]["accent"].startswith("#")
    tracker.config.menubar_display = "net_worth"
    tracker.config.privacy = True
    assert tracker.status_payload()["title"] == "••••"
    tracker.config.menubar_display = "symbol"
    tracker.config.menubar_symbol = "xeqt.to"
    assert tracker.status_payload()["title"].startswith("XEQT.TO 40.00 ▼")


def test_alerts_fire_once_then_rearm(tracker, store, fake, notifications):
    store.add_alert(Alert("AAPL", "above", 150))
    assert len(tracker.check_alerts()) == 1
    assert tracker.check_alerts() == []
    assert len(notifications) == 1
    fake.set_quote("AAPL", 100, 100)
    tracker.market.clear_cache()
    assert tracker.check_alerts() == [] and not store.alerts()[0].triggered_at
    fake.set_quote("AAPL", 160, 100)
    tracker.market.clear_cache()
    assert len(tracker.check_alerts()) == 1


def test_backfill_rebuilds_daily_history(tracker, store, fake):
    days = [(date.today() - timedelta(days=n)).isoformat() for n in (3, 2, 1, 0)]
    acct = store.add_account(Account(name="Main"))
    store.add_transaction(
        Transaction(
            account_id=acct.id, type=TxnType.BUY, date=days[0], symbol="AAPL", quantity=10, price=100, currency="USD"
        )
    )
    fake.set_history("AAPL", dict(zip(days, [100, 110, 120, 130], strict=True)))
    fake.set_history("USDCAD=X", dict.fromkeys(days, 1.3), currency="CAD")
    assert tracker.backfill() == 4
    snaps = store.snapshots()
    assert snaps[-1].net_worth == pytest.approx(10 * 130 * 1.3)
    assert snaps[0].contributions == pytest.approx(1000 * 1.3)
    perf = tracker.performance(tracker.valuation(record=False))
    assert perf.twr_pct == pytest.approx(30, rel=1e-3)


def test_tax_years_and_room(tracker, store, fake):
    acct = store.add_account(Account(name="Taxable"))
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.BUY,
            date="2025-01-02",
            symbol="AAPL",
            quantity=1,
            price=100,
            currency="USD",
        )
    )
    store.add_transaction(
        Transaction(
            account_id=acct.id,
            type=TxnType.SELL,
            date="2025-03-03",
            symbol="AAPL",
            quantity=1,
            price=150,
            currency="USD",
        )
    )
    # Cost at the buy date's rate (US$100 x 1.30 = C$130), proceeds at the
    # sale date's (US$150 x 1.40 = C$210): C$80, not the US$50 gain x 1.40 = C$70
    # that converting only at the sale date would give.
    fake.set_history("USDCAD=X", {"2025-01-02": 1.3, "2025-03-01": 1.4}, currency="CAD")
    years, report = tracker.tax_years()
    assert years[0].year == 2025 and years[0].net_gain == pytest.approx(80)
    assert report.issues == [] and not years[0].missing_fx
    # The FX series was requested from a week before the first purchase, not the first sale.
    fx_calls = [params for url, params in fake.calls if "USDCAD" in url]
    assert date.fromtimestamp(fx_calls[-1]["period1"]) <= date(2024, 12, 26)
    tfsa = store.add_account(Account(name="TFSA", type=AccountType.TFSA))
    store.set_room("TFSA", date.today().year, 7000)
    store.add_transaction(Transaction(account_id=tfsa.id, type=TxnType.DEPOSIT, amount=2000, currency="CAD"))
    ((status, members),) = tracker.room()
    assert status.remaining == pytest.approx(5000) and members[0].name == "TFSA"


def _buy(store, acct, day, qty, price, ccy="USD"):
    store.add_transaction(
        Transaction(
            account_id=acct.id, type=TxnType.BUY, date=day, symbol="AAPL", quantity=qty, price=price, currency=ccy
        )
    )


def test_backfill_converts_flows_at_their_own_fx(tracker, store, fake):
    days = [(date.today() - timedelta(days=n)).isoformat() for n in (3, 2, 1, 0)]
    acct = store.add_account(Account(name="Main"))
    _buy(store, acct, days[0], 10, 100)
    _buy(store, acct, days[2], 5, 100)
    fake.set_history("AAPL", dict.fromkeys(days, 100.0))  # flat price: any TWR != 0 is an FX artefact
    fake.set_history("USDCAD=X", dict(zip(days, [1.3, 1.3, 1.4, 1.5], strict=True)), currency="CAD")
    assert tracker.backfill() == 4
    snaps = store.snapshots()
    assert snaps[0].contributions == pytest.approx(1000 * 1.3)
    assert snaps[-1].contributions == pytest.approx(1000 * 1.3 + 500 * 1.4)
    # net worth rises with the rate, and only that shows up as return (not the revalued contributions)
    assert snaps[-1].net_worth == pytest.approx(1500 * 1.5)
    perf = tracker.performance(tracker.valuation(record=False))
    assert perf.twr_pct == pytest.approx(((1300 / 1300) * (1400 / 1300) * (2250 / 2100) - 1) * 100, rel=1e-6)


def test_backfill_defers_flow_until_fx_exists(tracker, store, fake):
    days = [(date.today() - timedelta(days=n)).isoformat() for n in (3, 2, 1, 0)]
    acct = store.add_account(Account(name="Main"))
    _buy(store, acct, days[0], 10, 100)
    fake.set_history("AAPL", dict.fromkeys(days, 100.0))
    fake.set_history("USDCAD=X", dict.fromkeys(days[1:], 1.3), currency="CAD")  # no rate on the buy day
    assert tracker.backfill() == 3
    snaps = store.snapshots()
    assert snaps[0].date == days[1]
    assert all(s.contributions == pytest.approx(1300) for s in snaps)  # never 0 × amount


def test_record_snapshot_is_incremental(tracker, store):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    acct = store.add_account(Account(name="Main"))
    _buy(store, acct, yesterday, 10, 100)
    _buy(store, acct, date.today().isoformat(), 5, 100)
    store.upsert_snapshot(Snapshot(yesterday, 1300, 1300, 1300, "CAD", {}))
    view = tracker.valuation()
    assert store.latest_snapshot().date == date.today().isoformat()
    assert store.latest_snapshot().contributions == pytest.approx(1300 + 500 * 1.35)
    tracker.valuation()  # a second refresh must not compound today's flows again
    assert store.latest_snapshot().contributions == pytest.approx(1300 + 500 * 1.35)
    # With no earlier snapshot the whole history converts at spot
    store.upsert_snapshots([])
    store._exec("DELETE FROM snapshots")
    tracker.record_snapshot(view, view.fx)
    assert store.latest_snapshot().contributions == pytest.approx(1500 * 1.35)


def test_stale_fx_marks_view_stale(store):
    acct = Account(name="Main", id=1)
    state = replay(
        [
            Transaction(
                account_id=1, type=TxnType.BUY, date="2024-01-02", symbol="AAPL", quantity=1, price=100, currency="USD"
            )
        ],
        {1: acct},
    )
    q = Quote(symbol="AAPL", price=100, prev_close=100, currency="USD")
    fresh = build_view(state, {1: acct}, {}, {"AAPL": q}, FxRates("CAD", {"USD": 1.3}))
    assert not fresh.stale
    cached = build_view(state, {1: acct}, {}, {"AAPL": q}, FxRates("CAD", {"USD": 1.3}, stale=True))
    assert cached.stale
