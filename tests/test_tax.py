"""Tax engine (tax.py): pooled ACB, trade-date FX, superficial losses, transfers.

Every expected figure is worked out by hand in the comments, the way CRA's
own examples lay them out, so a failing test says which rule broke.
"""

import pytest

from marketpulse.analytics import capital_gains
from marketpulse.ledger import replay
from marketpulse.models import Account, AccountType, Transaction, TxnType
from marketpulse.tax import DENIED_REGISTERED, DENIED_SUPERFICIAL, compute, fx_lookup

QT = 1  # Questrade non-registered (taxable)
WS = 2  # Wealthsimple non-registered (taxable)
TFSA = 3
ACCOUNTS = {
    QT: Account(name="Questrade", id=QT),
    WS: Account(name="Wealthsimple", id=WS),
    TFSA: Account(name="TFSA", id=TFSA, type=AccountType.TFSA),
}
_ids = iter(range(1, 10_000))


def txn(kind, day, symbol="X", qty=0.0, price=0.0, *, account=QT, fees=0.0, amount=0.0, ccy="CAD", **kw):
    return Transaction(
        account_id=account,
        type=kind,
        date=day,
        symbol=symbol,
        quantity=qty,
        price=price,
        fees=fees,
        amount=amount,
        currency=ccy,
        id=next(_ids),
        **kw,
    )


def cad(day, ccy):
    """FX for all-CAD tests: every rate is 1."""
    return 1.0


def run(txns, fx=cad, today="2030-01-01"):
    return compute(txns, ACCOUNTS, fx, today=today)


# ── Pooled ACB ────────────────────────────────────────────────────────────────


def test_acb_is_pooled_across_taxable_accounts():
    # 100 @ $10 at Questrade + 100 @ $20 at Wealthsimple = 200 units, ACB $3,000, $15/unit.
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=100, price=10, account=QT),
        txn(TxnType.BUY, "2024-01-02", qty=100, price=20, account=WS),
        txn(TxnType.SELL, "2024-06-01", qty=100, price=15, account=QT),
    ]
    (d,) = run(txns).dispositions
    # CRA: 100 x $15 pooled ACB = $1,500 against $1,500 proceeds: no gain.
    assert d.acb == pytest.approx(1500) and d.gain == pytest.approx(0)
    # The per-account ledger (what the holdings screen shows) still says +$500.
    assert replay(txns, ACCOUNTS).realized[0].gain == pytest.approx(500)


def test_registered_holdings_stay_out_of_the_pool():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=100, account=TFSA),
        txn(TxnType.BUY, "2024-01-01", qty=10, price=10, account=QT),
        txn(TxnType.SELL, "2024-06-01", qty=10, price=10, account=QT),
        txn(TxnType.SELL, "2024-06-01", qty=10, price=500, account=TFSA),  # never reported
    ]
    (d,) = run(txns).dispositions
    assert d.account_id == QT and d.acb == pytest.approx(100) and d.gain == pytest.approx(0)


@pytest.mark.parametrize("adjustment_fx", [1.5, None])
def test_non_cash_acb_increase_updates_the_taxable_pool_at_historical_fx(adjustment_fx):
    # Two taxable accounts have 20 units and a combined CAD 300 in cost.
    # The USD 20 adjustment adds CAD 30 at its own date's exchange rate.
    # Selling half the pool for CAD 200 then uses CAD 165 of ACB instead of 150.
    adjustment = txn(TxnType.ACB_INCREASE, "2024-04-02", amount=20, ccy="USD", account=QT)
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=10, ccy="USD", account=QT),
        txn(TxnType.BUY, "2024-01-02", qty=10, price=20, account=WS),
        txn(TxnType.BUY, "2024-01-02", qty=5, price=10, account=TFSA),
        adjustment,
        txn(adjustment.type, "2024-04-02", amount=100, account=TFSA),
        txn(TxnType.SELL, "2024-06-01", qty=10, price=20, account=WS),
    ]

    def fx(day, ccy):
        return adjustment_fx if (day, ccy) == (adjustment.date, "USD") else 1.0

    report = run(txns, fx)
    (sale,) = report.dispositions
    assert sale.complete is (adjustment_fx is not None)
    if sale.complete:
        assert (sale.acb, sale.gain) == pytest.approx((165, 35))
    else:
        (year,) = capital_gains(report)
        assert year.missing_fx == [sale] and year.net_gain == 0


def test_single_cad_account_matches_the_per_account_ledger():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=30, fees=5),
        txn(TxnType.BUY, "2024-02-01", qty=10, price=40),
        txn(TxnType.SELL, "2024-03-01", qty=5, price=50, fees=2),
    ]
    assert run(txns).dispositions[0].gain == pytest.approx(replay(txns, ACCOUNTS).realized[0].gain)


def test_splits_keep_acb_and_roc_beyond_acb_is_a_gain():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=10),  # ACB $100
        txn(TxnType.SPLIT, "2024-02-01", ratio=2),  # 20 units, still $100
        txn(TxnType.SELL, "2024-03-01", qty=10, price=6),  # ACB $50, proceeds $60
        txn(TxnType.ROC, "2024-04-01", amount=80),  # $50 left, $80 returned: $30 deemed gain
    ]
    sale, roc = run(txns).dispositions
    assert sale.gain == pytest.approx(10)
    assert (roc.kind, roc.gain) == ("roc", pytest.approx(30))


def test_open_pools_are_reported_after_the_replay():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=10, account=QT),
        txn(TxnType.BUY, "2024-01-01", qty=10, price=30, account=WS),
        txn(TxnType.BUY, "2024-01-01", "GONE", qty=1, price=1),
        txn(TxnType.SELL, "2024-01-02", "GONE", qty=1, price=1),
    ]
    pools = run(txns).pools
    assert set(pools) == {"X"}  # fully sold pools are dropped
    assert pools["X"].quantity == 20 and pools["X"].acb_per_unit == pytest.approx(20)


# ── Foreign currency: each leg at its own date's rate ─────────────────────────


def usd(rates):
    """FX lookup with a USD rate per date; CAD is always 1."""
    return lambda day, ccy: 1.0 if ccy == "CAD" else rates.get(day)


def test_cost_and_proceeds_are_converted_at_their_own_dates():
    # Buy 10 AAPL @ US$100 + US$5 commission when USD/CAD = 1.25 → ACB C$1,256.25
    # Sell 10 @ US$100 − US$5 commission when USD/CAD = 1.40    → proceeds C$1,393.00
    # A US$10 loss is a C$136.75 *gain*: the dollar rose while you held.
    txns = [
        txn(TxnType.BUY, "2024-01-02", "AAPL", 10, 100, fees=5, ccy="USD"),
        txn(TxnType.SELL, "2025-01-02", "AAPL", 10, 100, fees=5, ccy="USD"),
    ]
    (d,) = run(txns, usd({"2024-01-02": 1.25, "2025-01-02": 1.40})).dispositions
    assert d.acb == pytest.approx(1256.25)
    assert d.proceeds == pytest.approx(1393.0)
    assert d.gain == pytest.approx(136.75)
    assert d.fx == 1.40 and d.currency == "USD" and d.complete


def test_pooled_cost_blends_purchases_made_at_different_rates():
    txns = [
        txn(TxnType.BUY, "2024-01-02", "AAPL", 10, 100, ccy="USD"),  # C$1,300 at 1.30
        txn(TxnType.BUY, "2024-06-03", "AAPL", 10, 100, ccy="USD"),  # C$1,400 at 1.40
        txn(TxnType.SELL, "2025-01-02", "AAPL", 10, 100, ccy="USD"),  # C$1,350 at 1.35
    ]
    (d,) = run(txns, usd({"2024-01-02": 1.30, "2024-06-03": 1.40, "2025-01-02": 1.35})).dispositions
    assert d.acb == pytest.approx(1350) and d.gain == pytest.approx(0)


def test_missing_fx_marks_rows_incomplete_and_keeps_them_out_of_totals():
    txns = [
        txn(TxnType.BUY, "2024-01-02", "AAPL", 1, 100, ccy="USD"),  # no rate for this day
        txn(TxnType.SELL, "2024-02-01", "AAPL", 1, 150, ccy="USD"),
        # Fresh pool, bought after day +30 so it can't hold a loss the guessed sale might have had.
        txn(TxnType.BUY, "2024-03-04", "AAPL", 1, 100, ccy="USD"),
        txn(TxnType.SELL, "2024-04-01", "AAPL", 1, 150, ccy="USD"),
    ]
    report = run(txns, usd({"2024-02-01": 1.3, "2024-03-04": 1.3, "2024-04-01": 1.3}))
    first, second = report.dispositions
    assert not first.complete and second.complete  # the gap doesn't poison later pools
    (year,) = capital_gains(report)
    assert year.net_gain == pytest.approx(65) and year.missing_fx == [first]


@pytest.mark.parametrize(
    ("rates", "estimated_gain"),
    [
        ({}, 0.0),  # no rate for either leg: C$0 cost, C$0 proceeds
        ({"2024-02-01": 1.35}, 1350.0),  # no rate for the purchase only: it looks free
    ],
    ids=["no-rates", "purchase-rate-missing"],
)
def test_a_guessed_gain_with_a_replacement_in_the_window_leaves_the_replacement_incomplete(rates, estimated_gain):
    # With a real rate of 1.40 on 2023-12-01 the first sale is a C$50 loss (C$1,400 cost, C$1,350
    # proceeds), superficial because the replacement is still held at day +30, so the denied C$50
    # would be part of the replacement's cost. Without the rate the estimate shows no loss, but
    # it is only a guess: the replacement's cost, and the gain on selling it, are guesses too.
    fx = usd({**rates, "2024-02-15": 1.35, "2024-06-03": 1.35})
    txns = [
        txn(TxnType.BUY, "2023-12-01", "AAPL", 10, 100, ccy="USD"),  # no rate
        txn(TxnType.SELL, "2024-02-01", "AAPL", 10, 100, ccy="USD"),
        txn(TxnType.BUY, "2024-02-15", "AAPL", 10, 90, ccy="USD"),  # day +14, known rate, still held
    ]
    held = run(txns, fx)
    (first,) = held.dispositions
    assert not first.complete and first.gain == pytest.approx(estimated_gain) and not first.superficial
    assert held.pools["AAPL"].incomplete  # before the fix: the replacement pool looked complete

    report = run([*txns, txn(TxnType.SELL, "2024-06-03", "AAPL", 10, 120, ccy="USD")], fx)
    first, later = report.dispositions
    assert not later.complete  # before the fix: complete, at a C$405 gain that leaves out the denied loss
    (year,) = capital_gains(report)
    assert year.net_gain == 0 and year.missing_fx == [first, later]


def test_a_guessed_gain_on_a_partial_sale_with_a_replacement_leaves_the_rest_of_the_pool_incomplete():
    # Shares received at no cost, then half sold for less than the commission with no rate:
    # the estimate is C$0, but at any real rate it is a loss, and a superficial one, since more
    # were bought back within 30 days. The denied part would go into the units still held.
    fx = usd({"2024-01-02": 1.30, "2024-02-15": 1.35, "2024-06-03": 1.35})
    txns = [
        txn(TxnType.BUY, "2024-01-02", "AAPL", 20, 0, ccy="USD"),  # C$0 cost, known
        txn(TxnType.SELL, "2024-02-01", "AAPL", 10, 1, fees=15, ccy="USD"),  # US$-5 net, no rate
        txn(TxnType.BUY, "2024-02-15", "AAPL", 10, 1, ccy="USD"),  # day +14, still held
        txn(TxnType.SELL, "2024-06-03", "AAPL", 20, 2, ccy="USD"),
    ]
    first, later = run(txns, fx).dispositions
    assert not first.complete and first.gain == pytest.approx(0)
    assert not later.complete  # before the fix: complete


@pytest.mark.parametrize(
    "replacement",
    [
        txn(TxnType.BUY, "2024-03-03", "AAPL", 10, 90, ccy="USD"),  # day +31: outside the window
        txn(TxnType.BUY, "2024-02-15", "AAPL", 10, 90, ccy="USD", account=TFSA),  # no taxable cost to add to
    ],
    ids=["after-the-window", "in-a-tfsa"],
)
def test_a_guessed_gain_without_a_taxable_replacement_in_the_window_leaves_later_sales_alone(replacement):
    fx = usd({"2024-02-01": 1.35, "2024-02-15": 1.35, "2024-03-03": 1.35, "2024-06-03": 1.35})
    txns = [
        txn(TxnType.BUY, "2023-12-01", "AAPL", 10, 100, ccy="USD"),  # no rate
        txn(TxnType.SELL, "2024-02-01", "AAPL", 10, 100, ccy="USD"),
        replacement,
        txn(TxnType.BUY, "2024-03-03", "AAPL", 10, 90, ccy="USD"),  # day +31
        txn(TxnType.SELL, "2024-06-03", "AAPL", 10, 120, ccy="USD", account=QT),
    ]
    first, later = run(txns, fx).dispositions
    assert not first.complete  # the guessed sale is still flagged on its own
    # 10 x US$120 x 1.35 = C$1,620 against 10 x US$90 x 1.35 = C$1,215 of pooled cost, all known.
    assert later.complete and later.acb == pytest.approx(1215) and later.gain == pytest.approx(405)


def test_a_known_gain_with_a_replacement_in_the_window_leaves_the_replacement_complete():
    fx = usd({"2023-12-01": 1.30, "2024-02-01": 1.35, "2024-02-15": 1.35, "2024-06-03": 1.35})
    txns = [
        txn(TxnType.BUY, "2023-12-01", "AAPL", 10, 100, ccy="USD"),  # C$1,300
        txn(TxnType.SELL, "2024-02-01", "AAPL", 10, 110, ccy="USD"),  # C$1,485: a known C$185 gain
        txn(TxnType.BUY, "2024-02-15", "AAPL", 10, 90, ccy="USD"),  # C$1,215, bought back within 30 days
        txn(TxnType.SELL, "2024-06-03", "AAPL", 10, 120, ccy="USD"),  # C$1,620
    ]
    first, later = run(txns, fx).dispositions
    assert first.complete and first.gain == pytest.approx(185) and not first.superficial
    assert later.complete and later.acb == pytest.approx(1215) and later.gain == pytest.approx(405)


def test_fx_lookup_takes_the_last_close_on_or_before_the_day():
    fx = fx_lookup({"USD": {"2024-01-05": 1.33, "2024-01-08": 1.34}}, "CAD")
    assert fx("2024-01-06", "USD") == 1.33  # Saturday → Friday's close
    assert fx("2024-01-08", "usd") == 1.34
    assert fx("2024-01-01", "USD") is None  # before the series starts
    assert fx("2024-01-06", "EUR") is None
    assert fx("2024-01-06", "CAD") == fx("2024-01-06", "") == 1.0


# ── Superficial losses ────────────────────────────────────────────────────────


def test_averaging_down_then_selling_is_fully_superficial_and_the_loss_moves_to_acb():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=100, price=10),  # $1,000
        txn(TxnType.BUY, "2024-03-01", qty=100, price=6),  # $600 → 200 units, $8/unit
        txn(TxnType.SELL, "2024-03-10", qty=100, price=5),  # ACB $800, proceeds $500: −$300
        txn(TxnType.SELL, "2024-06-01", qty=100, price=5),  # clean sale, outside any window
    ]
    first, second = run(txns).dispositions
    # S=100 sold, P=100 bought 30 days either side (Mar 1), B=100 still held Apr 9 → 100% denied.
    assert (first.acquired_in_window, first.held_after_window) == (100, 100)
    assert first.denied == pytest.approx(300) and first.denied_reason == DENIED_SUPERFICIAL
    assert first.allowed_gain == pytest.approx(0)
    # The $300 went into the remaining shares' ACB: $800 + $300 = $1,100 → −$600 on the second sale.
    assert second.acb == pytest.approx(1100) and not second.superficial
    # Over both sales the full economic loss ($1,600 cost, $1,000 back) is still claimed, just later.
    assert first.allowed_gain + second.allowed_gain == pytest.approx(-600)


def test_partial_repurchase_denies_a_proportional_share():
    txns = [
        txn(TxnType.BUY, "2023-01-01", qty=100, price=10),
        txn(TxnType.SELL, "2024-03-01", qty=100, price=8),  # −$200
        txn(TxnType.BUY, "2024-03-15", qty=30, price=8),
    ]
    report = run(txns)
    (d,) = report.dispositions
    # min(S=100, P=30, B=30) / 100 = 30% of $200 = $60 denied.
    assert d.denied == pytest.approx(60) and d.allowed_gain == pytest.approx(-140)
    # The pool was empty at the sale, so the $60 waits and lands on the Mar 15 buy.
    assert report.pools["X"].acb == pytest.approx(30 * 8 + 60)


def test_buying_after_a_forward_split_uses_sale_date_units():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=15, price=100),
        txn(TxnType.SELL, "2024-03-01", qty=10, price=80),  # $200 loss on 10 pre-split shares
        txn(TxnType.SPLIT, "2024-03-08", ratio=2),
        txn(TxnType.BUY, "2024-03-15", qty=10, price=40),  # equivalent to 5 pre-split shares
    ]
    report = run(txns)
    (d,) = report.dispositions
    # 20 shares remain at the end of the window, equivalent to 10 on the sale date.
    assert (d.acquired_in_window, d.held_after_window) == (5, 10)
    assert d.denied == pytest.approx(100) and d.allowed_gain == pytest.approx(-100)
    assert report.pools["X"].acb == pytest.approx(500 + 400 + 100)


def test_buying_before_a_split_and_selling_after_compares_post_split_units():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=20, price=100),
        txn(TxnType.BUY, "2024-03-01", qty=5, price=100, account=TFSA),
        txn(TxnType.SPLIT, "2024-03-08", ratio=2),
        txn(TxnType.SPLIT, "2024-03-08", ratio=2, account=TFSA),
        txn(TxnType.SELL, "2024-03-12", qty=20, price=40),  # $200 loss on 20 post-split shares
    ]
    (d,) = run(txns).dispositions
    # The five acquired shares became ten by the sale, so half the loss is denied.
    assert (d.acquired_in_window, d.held_after_window) == (10, 30)
    assert d.denied == pytest.approx(100)


def test_reverse_split_does_not_reduce_the_equivalent_shares_still_held():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=100),
        txn(TxnType.SELL, "2024-03-01", qty=10, price=80),
        txn(TxnType.BUY, "2024-03-08", qty=10, price=80, account=TFSA),
        txn(TxnType.SPLIT, "2024-03-15", ratio=0.5, account=TFSA),
    ]
    (d,) = run(txns).dispositions
    # Five post-split shares represent all ten shares sold, so the $200 loss is fully denied.
    assert (d.acquired_in_window, d.held_after_window) == (10, 10)
    assert d.denied == pytest.approx(200)


def test_split_replacement_acb_uses_comparable_units_across_accounts():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=100),
        txn(TxnType.SELL, "2024-03-01", qty=10, price=80),
        txn(TxnType.BUY, "2024-03-08", qty=2, price=80),
        txn(TxnType.BUY, "2024-03-08", qty=4, price=80, account=TFSA),
        txn(TxnType.SPLIT, "2024-03-08", ratio=2),
        txn(TxnType.SPLIT, "2024-03-08", ratio=2, account=TFSA),
        txn(TxnType.BUY, "2024-03-15", qty=8, price=40),
    ]
    report = run(txns)
    (d,) = report.dispositions
    # Same-day buys are before the split in ledger order. The two split entries describe
    # the same event. Six of the ten sale-date replacement shares are taxable.
    assert (d.acquired_in_window, d.held_after_window) == (10, 10)
    assert d.denied == pytest.approx(200)
    assert report.pools["X"].acb == pytest.approx(160 + 320 + 120)


def test_split_day_purchase_in_an_account_without_a_split_uses_post_split_units():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=100),
        txn(TxnType.BUY, "2024-01-01", qty=1, price=100, account=TFSA),
        txn(TxnType.SELL, "2024-03-01", qty=10, price=80),
        txn(TxnType.SPLIT, "2024-03-08", ratio=2, account=TFSA),
        txn(TxnType.BUY, "2024-03-08", qty=10, price=40),
    ]
    report = run(txns)
    (d,) = report.dispositions
    # The taxable account was empty at the split. Its ten new shares represent
    # five sale-date shares while the TFSA still holds one in sale-date units.
    assert d.denied == pytest.approx(100)
    assert (d.acquired_in_window, d.held_after_window) == (5, 6)
    assert report.pools["X"].acb == pytest.approx(400 + 100)


def test_multiple_same_day_splits_in_one_account_are_each_counted():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=100),
        txn(TxnType.BUY, "2024-01-01", qty=3, price=100, account=TFSA),
        txn(TxnType.SELL, "2024-03-01", qty=10, price=80),
        txn(TxnType.SPLIT, "2024-03-08", ratio=2, account=TFSA),
        txn(TxnType.SPLIT, "2024-03-08", ratio=2, account=TFSA),
        txn(TxnType.BUY, "2024-03-15", qty=20, price=20),
    ]
    report = run(txns)
    (d,) = report.dispositions
    # Two successive 2-for-1 splits mean 20 shares now represent five on the sale date.
    assert d.denied == pytest.approx(100)
    assert (d.acquired_in_window, d.held_after_window) == (5, 8)
    assert report.pools["X"].acb == pytest.approx(400 + 100)


def test_one_split_recorded_on_different_dates_in_two_accounts_counts_once():
    txns = [
        txn(TxnType.BUY, "2024-01-02", qty=100, price=10),
        txn(TxnType.BUY, "2024-01-02", qty=40, price=10, account=WS),
        txn(TxnType.BUY, "2024-01-02", qty=20, price=10, account=TFSA),
        # Pool: 140 taxable units costing 1,400. The sale: ACB 1,000, proceeds 800, a 200 loss.
        txn(TxnType.SELL, "2024-03-01", qty=100, price=8),
        # One 2-for-1 split, which Wealthsimple records on 03-05 and the TFSA on 03-08.
        txn(TxnType.SPLIT, "2024-03-05", ratio=2, account=WS),
        txn(TxnType.BUY, "2024-03-06", qty=10, price=10, account=TFSA),  # before the TFSA's split row
        txn(TxnType.SPLIT, "2024-03-08", ratio=2, account=TFSA),
        txn(TxnType.BUY, "2024-03-20", qty=100, price=4),  # post-split: 50 sale-date units
    ]
    report = run(txns)
    (d,) = report.dispositions
    # In sale-date (pre-split) units, each holding converted by its own split row:
    #   P = 100 / 2 (Questrade, after the split) + 10 (TFSA, before its row) = 60
    #   B = (100 Questrade + 80 Wealthsimple + 60 TFSA) / 2 = 120 at the end of day +30
    #   denied = 200 x min(100, 60, 120) / 100 = 120
    # Counting each row as its own split (x4) gave P = 30, B = 60 and denied 60.
    assert (d.acquired_in_window, d.held_after_window) == (60, 120)
    assert d.denied == pytest.approx(120)
    # 50 of the 60 replacement units are taxable: 100 of the 120 joins the pool's cost,
    # which is Wealthsimple's 400 + 100 + Questrade's 400 replacement purchase.
    assert report.pools["X"].acb == pytest.approx(400 + 100 + 400)


@pytest.mark.parametrize("questrade_row_first", [True, False])
def test_same_day_split_rows_in_two_accounts_are_one_split_whatever_their_order(questrade_row_first):
    txns = [
        txn(TxnType.BUY, "2024-01-02", qty=100, price=10),
        txn(TxnType.SELL, "2024-02-20", qty=40, price=8),  # ACB 400, proceeds 320: an 80 loss
        txn(TxnType.SPLIT, "2024-03-01", ratio=2),  # the first of two 2-for-1 splits
        txn(TxnType.BUY, "2024-03-05", qty=20, price=5, account=WS),  # Wealthsimple held none on 03-01
    ]
    # The ledger orders same-day rows by id, so create them in the order under test.
    accounts = [QT, WS] if questrade_row_first else [WS, QT]
    txns += [txn(TxnType.SPLIT, "2024-03-10", ratio=2, account=a) for a in accounts]
    (d,) = run(txns).dispositions
    # Both 03-10 rows are the second split. In sale-date units:
    #   P = 20 Wealthsimple units bought after the first split / 2 = 10
    #   B = (240 Questrade + 40 Wealthsimple) / 4 = 70
    #   denied = 80 x min(40, 10, 70) / 40 = 20
    # The earlier code matched Wealthsimple's row to the first split when it came first,
    # which gave P = 20 and a denied loss of 40.
    assert (d.acquired_in_window, d.held_after_window) == (10, 70)
    assert d.denied == pytest.approx(20)


# A sale between the days two accounts post one split (#243). Questrade and Wealthsimple each
# hold 100 units bought at 10: a pool of 200 units costing 2,000. The 2-for-1 split is posted
# by Questrade on 03-01 and by Wealthsimple on 03-04. In post-split units the pool is 400 units
# at 5 each throughout.
def _staggered(*rows):
    return [
        txn(TxnType.BUY, "2024-01-02", qty=100, price=10),
        txn(TxnType.BUY, "2024-01-02", qty=100, price=10, account=WS),
        txn(TxnType.SPLIT, "2024-03-01", ratio=2),
        txn(TxnType.SPLIT, "2024-03-04", ratio=2, account=WS),
        *rows,
    ]


@pytest.mark.parametrize(
    ("day", "account", "qty", "acb"),
    [
        # Before either posting, both holdings are pre-split: 100 of 200 units, 1,000. Unchanged.
        ("2024-02-28", QT, 100, 1000),
        # Between the postings, 100 post-split Questrade units are 100 of 400 comparable units:
        # 500. Counting recorded units (Questrade 200 + Wealthsimple 100) gave 2,000 x 100 / 300.
        ("2024-03-02", QT, 100, 500),
        # 50 pre-split Wealthsimple units are 100 post-split units: also 500. Counted as
        # recorded, they took 2,000 x 50 / 300 = 333.33.
        ("2024-03-02", WS, 50, 500),
        # On the day of Wealthsimple's row its split comes first: 100 of 400 units. Unchanged.
        ("2024-03-04", QT, 100, 500),
    ],
)
def test_a_sale_between_two_postings_of_one_split_uses_comparable_units(day, account, qty, acb):
    report = run(_staggered(txn(TxnType.SELL, day, qty=qty, price=4, account=account)))
    (d,) = report.dispositions
    assert d.acb == pytest.approx(acb)
    assert d.proceeds == pytest.approx(qty * 4)
    assert d.denied == 0  # nothing bought in the window
    # What is left is 2,000 - acb, and every unit held after both postings costs 5.
    pool = report.pools["X"]
    assert pool.acb == pytest.approx(2000 - acb)
    assert pool.acb_per_unit == pytest.approx(5)


def test_the_issue_example_and_a_later_sale_of_the_rest():
    report = run(
        _staggered(
            txn(TxnType.SELL, "2024-03-02", qty=100, price=4),
            txn(TxnType.SELL, "2024-06-03", qty=100, price=6),
            txn(TxnType.SELL, "2024-06-03", qty=200, price=6, account=WS),
        )
    )
    between, *rest = report.dispositions
    # #243: ACB 500 and a 100 loss, where recorded units gave ACB 666.67 and a 266.67 loss.
    assert between.acb == pytest.approx(500) and between.gain == pytest.approx(-100)
    # The other 300 units carry the other 1,500 of cost, 5 each, so the pool's cost is used once.
    assert [d.acb for d in rest] == [pytest.approx(500), pytest.approx(1000)]
    assert sum(d.acb for d in report.dispositions) == pytest.approx(2000)
    assert report.pools == {}


def test_a_transfer_into_a_tfsa_between_postings_uses_comparable_units():
    report = run(_staggered(txn(TxnType.TRANSFER, "2024-03-02", qty=100, price=4, target_account_id=TFSA)))
    (d,) = report.dispositions
    assert d.kind == "deemed" and d.acb == pytest.approx(500)  # recorded units gave 666.67
    assert d.denied == pytest.approx(100)  # the loss on a move into a TFSA is denied outright


@pytest.mark.parametrize("exit_row", ["sell", "transfer"])
def test_selling_all_units_before_the_accounts_own_split_row_uses_comparable_units(exit_row):
    # Wealthsimple disposes of all 100 of its pre-split units on 03-02, then records the split on
    # 03-04 with nothing left. The ledger ignores that row, but the units were pre-split: 200 of
    # 400 comparable units, so ACB 1,000. Without the row, 100 of 300 recorded units gave 666.67.
    exit = (
        txn(TxnType.SELL, "2024-03-02", qty=100, price=4, account=WS)
        if exit_row == "sell"
        else txn(TxnType.TRANSFER, "2024-03-02", qty=100, price=4, account=WS, target_account_id=TFSA)
    )
    report = run(_staggered(exit))
    (d,) = report.dispositions
    assert d.acb == pytest.approx(1000)
    pool = report.pools["X"]  # Questrade's 200 post-split units keep the other 1,000
    assert pool.acb == pytest.approx(1000) and pool.acb_per_unit == pytest.approx(5)


def test_a_split_row_in_an_account_holding_none_changes_nothing():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=100),
        txn(TxnType.SELL, "2024-03-01", qty=10, price=80),  # a 200 loss
        txn(TxnType.BUY, "2024-03-15", qty=5, price=80),
    ]
    stray = txn(TxnType.SPLIT, "2024-03-08", ratio=2, account=WS)
    assert [i.message for i in replay([*txns, stray], ACCOUNTS).issues] == ["Split of X with nothing held"]
    # Five of the ten units sold were bought back and still held: half the loss is denied,
    # with or without the stray row (which used to halve the five to 2.5 and deny 50).
    for ledger in (txns, [*txns, stray]):
        report = run(ledger)
        (d,) = report.dispositions
        assert (d.acquired_in_window, d.held_after_window) == (5, 5)
        assert d.denied == pytest.approx(100)
        assert report.pools["X"].acb == pytest.approx(400 + 100)


def test_rebuying_in_a_tfsa_denies_the_loss_permanently():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=100),
        txn(TxnType.SELL, "2024-02-01", qty=10, price=80),  # −$200
        txn(TxnType.BUY, "2024-02-15", qty=10, price=81, account=TFSA),
    ]
    report = run(txns)
    (d,) = report.dispositions
    assert d.superficial and d.denied == pytest.approx(200)
    assert report.pools == {}  # nothing taxable to attach it to: it's gone


def test_no_denial_when_nothing_is_held_at_the_end_of_the_window():
    # Bought and sold inside the window: P=10 but B=0, so min(...) = 0.
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=100),
        txn(TxnType.SELL, "2024-01-20", qty=10, price=80),
    ]
    (d,) = run(txns).dispositions
    assert d.denied == 0 and not d.superficial and d.held_after_window == 0


def test_gains_and_distant_rebuys_are_never_superficial():
    gain = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=100),
        txn(TxnType.SELL, "2024-03-01", qty=10, price=120),
        txn(TxnType.BUY, "2024-03-02", qty=1, price=1),
    ]
    assert not run(gain).dispositions[0].superficial
    distant = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=100),
        txn(TxnType.SELL, "2024-03-01", qty=10, price=80),
        txn(TxnType.BUY, "2024-04-01", qty=10, price=80),  # day +31
    ]
    assert not run(distant).dispositions[0].superficial


def test_a_window_that_has_not_closed_is_marked_provisional():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=100),
        txn(TxnType.SELL, "2024-06-01", qty=10, price=80),
        txn(TxnType.BUY, "2024-06-05", qty=10, price=80),
    ]
    (d,) = run(txns, today="2024-06-10").dispositions
    assert d.superficial and d.window_open  # today's holdings stand in for day +30
    (closed,) = run(txns, today="2024-08-01").dispositions
    assert not closed.window_open


# ── In-kind transfers ─────────────────────────────────────────────────────────


def test_transfers_between_taxable_accounts_change_nothing():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=10, account=QT),
        txn(TxnType.TRANSFER, "2024-02-01", qty=10, target_account_id=WS),
        txn(TxnType.SELL, "2024-03-01", qty=10, price=12, account=WS),
    ]
    (d,) = run(txns).dispositions
    assert d.account_id == WS and d.gain == pytest.approx(20)


def test_contribution_in_kind_is_a_deemed_sale_and_losses_are_denied():
    gain = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=50),
        txn(TxnType.TRANSFER, "2024-02-01", qty=10, price=80, target_account_id=TFSA),
    ]
    (d,) = run(gain).dispositions
    assert (d.kind, d.gain, d.allowed_gain) == ("deemed", pytest.approx(300), pytest.approx(300))
    loss = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=50),
        txn(TxnType.TRANSFER, "2024-02-01", qty=10, price=30, target_account_id=TFSA),
    ]
    (d,) = run(loss).dispositions
    assert d.denied_reason == DENIED_REGISTERED and d.allowed_gain == pytest.approx(0)


def test_unpriced_transfers_across_the_registered_line_raise_issues():
    out = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=50),
        txn(TxnType.TRANSFER, "2024-02-01", qty=10, target_account_id=TFSA),
    ]
    report = run(out)
    assert report.dispositions == [] and report.pools == {}
    assert "deemed sale" in report.issues[0].message
    back = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=5, account=TFSA),
        txn(TxnType.TRANSFER, "2024-02-01", qty=10, account=TFSA, target_account_id=QT),
        txn(TxnType.SELL, "2024-03-01", qty=10, price=25),
    ]
    report = run(back)
    assert "market value" in report.issues[0].message
    assert not report.dispositions[0].complete  # cost unknown → kept out of totals


def test_withdrawal_in_kind_enters_the_pool_at_market_value():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=5, account=TFSA),
        txn(TxnType.TRANSFER, "2024-02-01", qty=10, price=20, account=TFSA, target_account_id=QT),
        txn(TxnType.SELL, "2024-03-01", qty=10, price=25),
    ]
    (d,) = run(txns).dispositions
    assert d.acb == pytest.approx(200) and d.gain == pytest.approx(50)  # the TFSA's growth stays tax-free


# ── Yearly totals ─────────────────────────────────────────────────────────────


def test_tax_years_group_and_total_allowed_gains():
    txns = [
        txn(TxnType.BUY, "2023-01-01", qty=10, price=10),
        txn(TxnType.SELL, "2023-06-01", qty=5, price=20),  # +$50 in 2023
        txn(TxnType.SELL, "2024-06-01", qty=5, price=8),  # −$10 in 2024
    ]
    y2024, y2023 = capital_gains(run(txns), inclusion_rate=0.5)
    assert (y2024.year, y2023.year) == (2024, 2023)
    assert y2023.net_gain == pytest.approx(50) and y2023.taxable == pytest.approx(25)
    assert y2024.net_gain == pytest.approx(-10) and y2024.taxable == 0  # a net loss isn't taxable


def test_roc_without_an_fx_rate_flags_the_pool():
    txns = [
        txn(TxnType.BUY, "2024-01-02", "VTI", 10, 100, ccy="USD"),
        txn(TxnType.ROC, "2024-02-01", "VTI", amount=50, ccy="USD"),  # no rate this day
        txn(TxnType.SELL, "2024-03-01", "VTI", 10, 100, ccy="USD"),
    ]
    (d,) = run(txns, usd({"2024-01-02": 1.3, "2024-03-01": 1.3})).dispositions
    assert not d.complete  # the ACB reduction is unknown, so the gain is too


# ── Quantities the ledger doesn't hold ────────────────────────────────────────
# ledger.replay() reports these as issues; the tax engine must only count what was held.


def test_selling_more_than_is_held_disposes_only_what_is_held():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=10),
        txn(TxnType.SELL, "2024-02-01", qty=15, price=12),  # 10 held: 10 × $12 − $100 = +$20
        txn(TxnType.SELL, "2024-03-01", "Y", qty=5, price=9),  # never bought: no disposition
    ]
    (d,) = run(txns).dispositions
    assert (d.symbol, d.quantity, d.gain) == ("X", 10, pytest.approx(20))


def test_moving_or_splitting_unheld_shares_changes_no_pool():
    txns = [
        txn(TxnType.TRANSFER, "2024-01-01", "Y", qty=5, price=10, target_account_id=WS),
        txn(TxnType.SPLIT, "2024-01-02", "Y", ratio=2),
        txn(TxnType.TRANSFER, "2024-01-03", "Y", qty=5, price=10, target_account_id=TFSA),
    ]
    report = run(txns)
    assert report.dispositions == [] and report.pools == {} and report.issues == []


def test_contribution_in_kind_beyond_the_holding_is_a_deemed_sale_of_the_holding():
    txns = [
        txn(TxnType.BUY, "2024-01-01", qty=10, price=50),
        txn(TxnType.TRANSFER, "2024-02-01", qty=15, price=80, target_account_id=TFSA),
    ]
    (d,) = run(txns).dispositions
    # 10 × $80 − $500 = +$300; the 5 extra units were never in the pool.
    assert (d.kind, d.quantity, d.gain) == ("deemed", 10, pytest.approx(300))
