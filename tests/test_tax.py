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
        txn(TxnType.BUY, "2024-03-01", "AAPL", 1, 100, ccy="USD"),  # fresh pool: fully known
        txn(TxnType.SELL, "2024-04-01", "AAPL", 1, 150, ccy="USD"),
    ]
    report = run(txns, usd({"2024-02-01": 1.3, "2024-03-01": 1.3, "2024-04-01": 1.3}))
    first, second = report.dispositions
    assert not first.complete and second.complete  # the gap doesn't poison later pools
    (year,) = capital_gains(report)
    assert year.net_gain == pytest.approx(65) and year.missing_fx == [first]


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
