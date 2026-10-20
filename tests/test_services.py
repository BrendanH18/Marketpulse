from dataclasses import replace
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
    archived = tracker.status_payload()
    assert archived["accounts"] == []  # archived accounts are hidden from lists and totals
    assert archived["net_worth"] == 0
    assert archived["movers"] == []
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


def test_archived_accounts_are_left_out_of_totals_and_pause_snapshots(tracker, store):
    main = store.add_account(Account(name="Main", track_cash=True))
    old = store.add_account(Account(name="Old", track_cash=True))
    for acct in (main, old):
        tracker.add_transaction(Transaction(account_id=acct.id, type=TxnType.DEPOSIT, amount=500, currency="CAD"))
        tracker.add_transaction(
            Transaction(account_id=acct.id, type=TxnType.BUY, symbol="AAPL", quantity=1, price=100, currency="USD")
        )
    both = tracker.valuation(record=False)
    old.archived = True
    store.update_account(old)
    view = tracker.valuation()
    assert view.net_worth == pytest.approx(both.net_worth / 2)
    assert {p.account.name for p in view.positions} == {"Main"}
    assert {c.account.name for c in view.cash} == {"Main"}
    assert [b.label for b in view.by_account] == ["Main"]
    assert view.archived_with_value == ["Old"]
    assert store.snapshots() == []  # a fake drop in value is never recorded
    # Asking for the archived account explicitly still shows it.
    assert tracker.valuation(account_id=old.id, record=False).net_worth == pytest.approx(both.net_worth / 2)


def test_emptied_archived_account_does_not_pause_snapshots(tracker, store):
    main = store.add_account(Account(name="Main"))
    old = store.add_account(Account(name="Old", track_cash=True))
    tracker.add_transaction(Transaction(account_id=old.id, type=TxnType.DEPOSIT, amount=100, currency="CAD"))
    tracker.add_transaction(Transaction(account_id=old.id, type=TxnType.WITHDRAWAL, amount=100, currency="CAD"))
    tracker.add_transaction(
        Transaction(account_id=main.id, type=TxnType.BUY, symbol="AAPL", quantity=1, price=100, currency="USD")
    )
    old.archived = True
    store.update_account(old)
    view = tracker.valuation()
    assert view.archived_with_value == []
    assert len(store.snapshots()) == 1


def test_backfill_refuses_while_an_archived_account_holds_value(tracker, store, fake):
    days = [(date.today() - timedelta(days=n)).isoformat() for n in (3, 2, 1, 0)]
    fake.set_history("AAPL", dict.fromkeys(days, 100.0))
    fake.set_history("USDCAD=X", dict.fromkeys(days, 1.0), currency="CAD")
    main = store.add_account(Account(name="Main"))
    old = store.add_account(Account(name="Old RRSP", type=AccountType.RRSP))
    _buy(store, main, days[0], 1, 100)
    _buy(store, old, days[0], 1, 100)
    old.archived = True
    store.update_account(old)
    calls = len(fake.calls)
    with pytest.raises(ValueError, match="Archived account Old RRSP still holds"):
        tracker.backfill()
    assert store.snapshots() == [] and len(fake.calls) == calls  # fails before any price request
    # Once it's emptied, history rebuilds and counts it on the days it still held AAPL.
    store.add_transaction(
        Transaction(
            account_id=old.saved_id,
            type=TxnType.SELL,
            date=days[2],
            symbol="AAPL",
            quantity=1,
            price=100,
            currency="USD",
        )
    )
    assert tracker.backfill() == 4
    by_day = {s.date: s.net_worth for s in store.snapshots()}
    assert by_day[days[0]] == pytest.approx(200)  # both accounts held 1 AAPL @ 100 (FX 1.0)
    assert by_day[days[3]] == pytest.approx(100)


def test_archiving_an_account_with_holdings_does_not_fake_a_loss(tracker, store):
    main = store.add_account(Account(name="Main"))
    old = store.add_account(Account(name="Old"))
    for acct in (main, old):
        tracker.add_transaction(
            Transaction(
                account_id=acct.id,
                type=TxnType.BUY,
                date="2024-01-02",
                symbol="AAPL",
                quantity=1,
                price=100,
                currency="USD",
            )
        )
    before_view = tracker.valuation(record=False)
    before = tracker.performance(before_view)
    old.archived = True
    store.update_account(old)
    view = tracker.valuation(record=False)
    after = tracker.performance(view)
    assert view.net_worth == pytest.approx(before_view.net_worth / 2)  # hidden from totals...
    assert view.value_for_returns == pytest.approx(before_view.net_worth)  # ...but not from returns
    assert after.total_gain == pytest.approx(before.total_gain)
    assert after.xirr_pct == pytest.approx(before.xirr_pct)


def test_an_unpriced_archived_holding_is_flagged_not_counted_as_zero(tracker, store):
    main = store.add_account(Account(name="Main"))
    old = store.add_account(Account(name="Old"))
    _buy(store, main, "2024-01-02", 1, 100)
    store.add_transaction(
        Transaction(
            account_id=old.id,
            type=TxnType.BUY,
            date="2024-01-02",
            symbol="NOPRICE",
            quantity=1,
            price=100,
            currency="USD",
        )
    )
    old.archived = True
    store.update_account(old)
    view = tracker.valuation(record=False)
    assert "NOPRICE in archived Old" in view.excluded
    assert view.archived_value == 0 and view.archived_with_value == ["Old"]


def test_a_refresh_spanning_a_restore_records_nothing_from_the_replaced_ledger(tracker, store, monkeypatch):
    acct = store.add_account(Account(name="Main"))
    buy = Transaction(account_id=acct.id, type=TxnType.BUY, date="2024-01-02", symbol="AAPL", quantity=1, price=100)
    store.add_transaction(buy)
    taken = store.backup()
    store.add_transaction(Transaction(account_id=acct.id, type=TxnType.DEPOSIT, date="2024-02-01", amount=5000))
    store.add_transaction(replace(buy, id=None, quantity=9))
    real_quotes = tracker.market.quotes

    def restore_while_quotes_load(symbols, **kwargs):
        store.restore(taken)  # e.g. `marketpulse backup restore` in a terminal, mid-refresh
        return real_quotes(symbols, **kwargs)

    monkeypatch.setattr(tracker.market, "quotes", restore_while_quotes_load)
    tracker.valuation()
    assert store.snapshots() == []  # that view valued ten shares the restored ledger doesn't have
    monkeypatch.setattr(tracker.market, "quotes", real_quotes)
    tracker.valuation()
    (snap,) = store.snapshots()
    assert snap.contributions == pytest.approx(100)  # only the restored ledger's one buy


def test_backfill_spanning_a_restore_writes_nothing(tracker, store, fake, monkeypatch):
    days = [(date.today() - timedelta(days=n)).isoformat() for n in (1, 0)]
    acct = store.add_account(Account(name="Main"))
    store.add_transaction(
        Transaction(account_id=acct.id, type=TxnType.BUY, date=days[0], symbol="AAPL", quantity=1, price=100)
    )
    taken = store.backup()
    fake.set_history("AAPL", dict(zip(days, [100, 110], strict=True)))
    fake.set_history("USDCAD=X", dict.fromkeys(days, 1.3), currency="CAD")
    real_closes = tracker.market.daily_closes
    restored = []

    def restore_while_closes_load(*args, **kwargs):
        if not restored:
            restored.append(store.restore(taken))
        return real_closes(*args, **kwargs)

    monkeypatch.setattr(tracker.market, "daily_closes", restore_while_closes_load)
    assert tracker.backfill() == 0 and restored and store.snapshots() == []
    assert tracker.backfill() == 2  # rebuilt from the restored ledger, once nothing replaced it midway


def test_a_save_spanning_a_restore_is_refused(tracker, store, monkeypatch):
    acct = store.add_account(Account(name="Main"))
    store.add_transaction(
        Transaction(account_id=acct.id, type=TxnType.BUY, date="2024-01-02", symbol="AAPL", quantity=10, price=100)
    )
    taken = store.backup()
    store.add_transaction(
        Transaction(account_id=acct.id, type=TxnType.BUY, date="2024-01-03", symbol="AAPL", quantity=20, price=100)
    )
    real_quote = tracker.market.quote

    def restore_while_currency_resolves(symbol):
        store.restore(taken)  # `marketpulse backup restore` in a terminal, mid-save
        return real_quote(symbol)

    monkeypatch.setattr(tracker.market, "quote", restore_while_currency_resolves)
    # Checked against 30 shares before the restore; the restored ledger has 10.
    sale = Transaction(account_id=acct.id, type=TxnType.SELL, date="2024-02-01", symbol="AAPL", quantity=25, price=1)
    with pytest.raises(ValueError, match="restored from a backup while this was being saved"):
        tracker.add_transaction(sale)
    assert [t.quantity for t in store.transactions()] == [10]
    monkeypatch.setattr(tracker.market, "quote", real_quote)
    with pytest.raises(ValueError, match="only 10 held"):
        tracker.add_transaction(replace(sale, currency=""))


# ── editing and deleting transactions ─────────────────────────────────────────


def _trade(acct, kind, day, qty, price, symbol="AAPL"):
    return Transaction(
        account_id=acct.id, type=kind, date=day, symbol=symbol, quantity=qty, price=price, currency="USD"
    )


def test_an_edit_recomputes_acb_and_realized_gain(tracker, store):
    acct = store.add_account(Account(name="Fictional TFSA", type=AccountType.TFSA))
    store.add_transaction(_trade(acct, TxnType.BUY, "2024-01-02", 10, 100))
    second = store.add_transaction(_trade(acct, TxnType.BUY, "2024-01-03", 10, 120))
    store.add_transaction(_trade(acct, TxnType.SELL, "2024-02-01", 5, 130))
    before = store.ledger()
    assert before.holdings[(acct.id, "AAPL")].avg_cost == pytest.approx(110)
    assert before.realized[0].gain == pytest.approx(100)  # 5 × (130 − 110)

    tracker.update_transaction(replace(second, price=140))
    after = store.ledger()
    assert after.holdings[(acct.id, "AAPL")].avg_cost == pytest.approx(120)
    assert after.realized[0].gain == pytest.approx(50)  # 5 × (130 − 120)


def test_an_edit_that_oversells_is_refused_and_changes_nothing(tracker, store):
    acct = store.add_account(Account(name="Main"))
    store.add_transaction(_trade(acct, TxnType.BUY, "2024-01-02", 10, 100))
    sale = store.add_transaction(_trade(acct, TxnType.SELL, "2024-02-01", 4, 110))
    with pytest.raises(ValueError, match=r"Not saved: on 2024-02-01, sell of 20\.0000 AAPL exceeds 10\.0000 held"):
        tracker.update_transaction(replace(sale, quantity=20))
    assert [t.quantity for t in store.transactions()] == [10, 4]


def test_a_backdated_edit_that_breaks_a_later_sale_is_refused(tracker, store):
    # Today's holdings are the same either way (bought 10, sold 10), so only a replay at each
    # entry's own date shows that the sale would come before the shares it sells.
    acct = store.add_account(Account(name="Main"))
    buy = store.add_transaction(_trade(acct, TxnType.BUY, "2024-01-02", 10, 100))
    sale = store.add_transaction(_trade(acct, TxnType.SELL, "2024-02-01", 10, 110))
    with pytest.raises(ValueError, match=rf"transaction #{sale.id} on 2024-02-01 would no longer add up"):
        tracker.update_transaction(replace(buy, date="2024-03-01"))
    assert store.transactions()[0].date == "2024-01-02"
    tracker.update_transaction(replace(buy, date="2024-01-15"))  # still before the sale
    assert store.transactions()[0].date == "2024-01-15"


def test_moving_a_purchase_to_another_account_is_refused_when_a_sale_needs_it(tracker, store):
    main = store.add_account(Account(name="Main"))
    other = store.add_account(Account(name="Other"))
    buy = store.add_transaction(_trade(main, TxnType.BUY, "2024-01-02", 10, 100))
    store.add_transaction(_trade(main, TxnType.SELL, "2024-02-01", 5, 110))
    with pytest.raises(ValueError, match="would no longer add up"):
        tracker.update_transaction(replace(buy, account_id=other.id))
    with pytest.raises(ValueError, match="Unknown account"):
        tracker.update_transaction(replace(buy, account_id=999))
    assert store.transactions()[0].account_id == main.id


def test_deleting_a_purchase_a_sale_needs_is_refused(tracker, store):
    acct = store.add_account(Account(name="Main"))
    buy = store.add_transaction(_trade(acct, TxnType.BUY, "2024-01-02", 10, 100))
    sale = store.add_transaction(_trade(acct, TxnType.SELL, "2024-02-01", 5, 110))
    with pytest.raises(ValueError, match=rf"Not deleted: transaction #{sale.id} on 2024-02-01"):
        tracker.delete_transaction(buy.saved_id)
    assert len(store.transactions()) == 2
    tracker.delete_transaction(sale.saved_id)
    tracker.delete_transaction(buy.saved_id)
    assert store.transactions() == []
    with pytest.raises(ValueError, match="No transaction #"):
        tracker.delete_transaction(buy.saved_id)


def test_problems_already_in_the_ledger_do_not_block_other_changes(tracker, store):
    acct = store.add_account(Account(name="Main"))
    # An oversell the add guard can't see: backdated before the purchase it relies on.
    buy = store.add_transaction(_trade(acct, TxnType.BUY, "2024-03-01", 10, 100))
    broken = store.add_transaction(_trade(acct, TxnType.SELL, "2024-02-01", 5, 110))
    other = store.add_transaction(_trade(acct, TxnType.BUY, "2024-01-02", 1, 50, symbol="MSFT"))
    assert [i.txn_id for i in store.ledger().issues] == [broken.id]
    tracker.update_transaction(replace(other, note="fixed a typo"))
    tracker.update_transaction(replace(broken, note="still to sort out"))
    tracker.update_transaction(replace(buy, price=101))
    assert [t.note for t in store.transactions() if t.id == broken.id] == ["still to sort out"]
    tracker.update_transaction(replace(broken, date="2024-03-02"))  # the fix
    assert store.ledger().issues == []


def test_an_edit_is_validated_like_a_new_entry(tracker, store):
    acct = store.add_account(Account(name="Main"))
    buy = store.add_transaction(_trade(acct, TxnType.BUY, "2024-01-02", 10, 100))
    with pytest.raises(ValueError, match="Quantity must be positive"):
        tracker.update_transaction(replace(buy, quantity=0))
    with pytest.raises(ValueError, match="future"):
        tracker.update_transaction(replace(buy, date=(date.today() + timedelta(days=2)).isoformat()))
    with pytest.raises(ValueError, match="hasn't been saved"):
        tracker.update_transaction(replace(buy, id=None))
    with pytest.raises(ValueError, match="No transaction #999"):
        tracker.update_transaction(replace(buy, id=999))
    tracker.update_transaction(replace(buy, symbol="XEQT.TO", currency=""))  # blank: resolved again
    assert store.transactions()[0].currency == "CAD"


def test_an_edit_or_delete_spanning_a_restore_is_refused(tracker, store):
    acct = store.add_account(Account(name="Main"))
    buy = store.add_transaction(_trade(acct, TxnType.BUY, "2024-01-02", 10, 100))
    taken = store.backup()
    store.add_transaction(_trade(acct, TxnType.BUY, "2024-01-03", 20, 100))
    restore_id = store.restore_id  # read before looking the entry up, as the CLI does
    store.restore(taken)  # `marketpulse backup restore` in another window, meanwhile
    with pytest.raises(ValueError, match="restored from a backup while this was being saved"):
        tracker.update_transaction(replace(buy, price=1), restore_id=restore_id)
    with pytest.raises(ValueError, match="restored from a backup while this was being deleted"):
        tracker.delete_transaction(buy.saved_id, restore_id=restore_id)
    assert [(t.quantity, t.price) for t in store.transactions()] == [(10, 100)]


def test_an_edit_with_a_non_iso_date_is_checked_at_the_date_it_is_stored_as(tracker, store):
    acct = store.add_account(Account(name="Main"))
    buy = store.add_transaction(_trade(acct, TxnType.BUY, "2024-01-02", 10, 100))
    store.add_transaction(_trade(acct, TxnType.SELL, "2024-02-01", 10, 110))
    # "01/31/2025" sorts before "2024-02-01" as text, but is stored as 2025-01-31: after the sale.
    with pytest.raises(ValueError, match="would no longer add up"):
        tracker.update_transaction(replace(buy, date="01/31/2025"))
    assert store.transactions()[0].date == "2024-01-02"


def test_an_entry_changed_or_replaced_since_it_was_loaded_is_refused(tracker, store):
    acct = store.add_account(Account(name="Main"))
    fee = store.add_transaction(Transaction(account_id=acct.id, type=TxnType.FEE, date="2024-01-02", amount=5))
    seen = store.transactions()[0].revision  # what the app's Activity row carries
    # Another window undoes the fee and records a deposit, which SQLite gives the same id.
    tracker.delete_transaction(fee.saved_id)
    deposit = store.add_transaction(
        Transaction(account_id=acct.id, type=TxnType.DEPOSIT, date="2024-01-03", amount=500)
    )
    assert deposit.id == fee.id
    with pytest.raises(ValueError, match=rf"#{fee.id} has changed since it was loaded"):
        tracker.delete_transaction(fee.saved_id, revision=seen)
    with pytest.raises(ValueError, match="has changed since it was loaded"):
        tracker.update_transaction(replace(store.transactions()[0], amount=1), revision=seen)
    assert [(t.type, t.amount) for t in store.transactions()] == [(TxnType.DEPOSIT, 500)]
    current = store.transactions()[0].revision
    tracker.update_transaction(replace(store.transactions()[0], note="checked"), revision=current)
    assert store.transactions()[0].revision != current  # any stored change moves it on
