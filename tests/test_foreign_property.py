"""Specified foreign property for form T1135 (tax.foreign_property, #179), on fictional ledgers.

Costs are pooled ACB in CAD at the end of each day. Every expected figure is worked out in the
comments, so a failing test says which rule broke.
"""

import pytest

from marketpulse.models import Account, AccountType, Asset, AssetClass, AssetKind, Transaction, TxnType
from marketpulse.tax import (
    T1135_DETAILED,
    T1135_NOT_REQUIRED,
    T1135_SIMPLIFIED,
    ForeignPropertyYear,
    compute,
    foreign_property,
    foreign_property_years,
    is_foreign_property,
)

TAXABLE = 1
MARGIN = 2
TFSA = 3
RRSP = 4
ACCOUNTS = {
    TAXABLE: Account(name="Fictional Taxable", id=TAXABLE),
    MARGIN: Account(name="Fictional Margin", id=MARGIN, type=AccountType.MARGIN),
    TFSA: Account(name="Fictional TFSA", id=TFSA, type=AccountType.TFSA),
    RRSP: Account(name="Fictional RRSP", id=RRSP, type=AccountType.RRSP),
}
_ids = iter(range(1, 10_000))


def txn(kind, day, symbol="FICTUS", qty=0.0, price=0.0, *, account=TAXABLE, ccy="CAD", **kw):
    return Transaction(
        account_id=account,
        type=kind,
        date=day,
        symbol=symbol,
        quantity=qty,
        price=price,
        currency=ccy,
        id=next(_ids),
        **kw,
    )


def cad(day, ccy):
    return 1.0


def usd_rates(day, ccy):
    """USD/CAD rises through 2024: 1.30 until March, 1.35 until July, then 1.40."""
    if ccy == "CAD":
        return 1.0
    return 1.30 if day < "2024-03-01" else 1.35 if day < "2024-07-01" else 1.40


def year(txns, y=2024, fx=cad, assets=None, today="2030-01-01") -> ForeignPropertyYear:
    return foreign_property(txns, ACCOUNTS, assets or {}, fx, y, today=today)


# ── What counts ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("symbol", "asset", "expected"),
    [
        ("FICTUS", None, True),  # no suffix: a US listing
        ("fictus", None, True),
        ("FICT.L", None, True),  # London
        ("FICT.DE", None, True),  # Xetra
        ("FICT-B", None, True),  # a US share class, not a crypto pair
        ("XFIC.TO", None, False),  # TSX: a Canadian-listed ETF of US stocks isn't foreign property
        ("XFIC.V", None, False),
        ("XFIC.NE", None, False),
        ("XFIC.CN", None, False),
        ("FICTCOIN-USD", None, False),  # crypto pairs
        ("FICTCOIN-CAD", None, False),
        ("USDCAD=X", None, False),
        ("^FICT", None, False),
        ("", None, False),
        ("FICTC", Asset("FICTC", asset_class=AssetClass.CRYPTO), False),
        ("FICMM", Asset("FICMM", asset_class=AssetClass.CASH), False),
        ("FICTUS", Asset("FICTUS", asset_class=AssetClass.ETF), True),
        ("GIC-FICT", Asset("GIC-FICT", AssetKind.FIXED_INCOME), False),
        ("CONDO-FICT", Asset("CONDO-FICT", AssetKind.MANUAL), False),
        ("HISA-FICT", Asset("HISA-FICT", AssetKind.CASH), False),
        # The setting wins, both ways, whatever the listing or kind.
        ("XFIC.TO", Asset("XFIC.TO", foreign_property=True), True),
        ("FICTUS", Asset("FICTUS", foreign_property=False), False),
        ("CONDO-FICT", Asset("CONDO-FICT", AssetKind.MANUAL, foreign_property=True), True),
    ],
)
def test_foreign_property_is_decided_by_listing_unless_set(symbol, asset, expected):
    assert is_foreign_property(symbol, asset) is expected


# ── Cost through the year ─────────────────────────────────────────────────────


def test_mid_year_peak_over_100k_is_flagged_even_when_the_year_ends_below():
    txns = [
        txn(TxnType.BUY, "2024-02-01", qty=400, price=150),  # $60,000
        txn(TxnType.BUY, "2024-05-10", qty=400, price=150),  # $120,000: over the line
        txn(TxnType.SELL, "2024-08-20", qty=600, price=160),  # 200 left at $150: $30,000
    ]
    y = year(txns)
    assert y.max_cost == pytest.approx(120_000) and y.max_cost_date == "2024-05-10"
    assert y.year_end_cost == pytest.approx(30_000) and y.as_of == "2024-12-31"
    assert y.status == T1135_SIMPLIFIED and not y.incomplete
    (h,) = y.holdings
    assert (h.symbol, h.max_cost, h.max_cost_date, h.year_end_cost) == ("FICTUS", 120_000, "2024-05-10", 30_000)
    # 600 sold at $160 against $150 ACB: $6,000.
    assert h.dispositions == 1 and h.gain == pytest.approx(6_000) and y.gain == pytest.approx(6_000)
    # 2025 starts with what 2024 left: $30,000 on January 1, and nothing happens after.
    following = year(txns, 2025)
    assert following.max_cost == pytest.approx(30_000) and following.max_cost_date == "2025-01-01"
    assert following.status == T1135_NOT_REQUIRED and following.holdings[0].dispositions == 0


def test_usd_purchases_are_converted_at_each_purchase_date_rate():
    txns = [
        txn(TxnType.BUY, "2024-02-01", qty=500, price=100, ccy="USD"),  # US$50,000 x 1.30 = $65,000
        txn(TxnType.BUY, "2024-06-03", qty=200, price=100, ccy="USD"),  # US$20,000 x 1.35 = $27,000
    ]
    y = year(txns, fx=usd_rates)
    # $92,000: under the line. At December's 1.40, US$70,000 would have been $98,000, and at a
    # later 1.45 it would have been $101,500 and wrongly flagged: cost never moves with the rate.
    assert y.max_cost == pytest.approx(92_000) and y.year_end_cost == pytest.approx(92_000)
    assert y.max_cost_date == "2024-06-03" and y.status == T1135_NOT_REQUIRED and y.currency == "CAD"


def test_registered_accounts_never_count():
    txns = [
        txn(TxnType.BUY, "2024-01-10", qty=1000, price=200, account=TFSA),
        txn(TxnType.BUY, "2024-01-10", qty=1000, price=200, account=RRSP),
        txn(TxnType.BUY, "2024-01-11", qty=100, price=200, account=MARGIN),  # $20,000 taxable
    ]
    y = year(txns)
    assert y.max_cost == pytest.approx(20_000) and y.status == T1135_NOT_REQUIRED


def test_moving_foreign_shares_into_a_registered_account_ends_their_cost():
    txns = [
        txn(TxnType.BUY, "2024-01-10", qty=1000, price=150),  # $150,000
        txn(TxnType.TRANSFER, "2024-03-01", qty=1000, price=150, target_account_id=TFSA),
    ]
    y = year(txns)
    assert y.max_cost == pytest.approx(150_000) and y.year_end_cost == 0
    assert y.holdings[0].dispositions == 1 and y.holdings[0].gain == 0  # the deemed sale, at cost


def test_canadian_listed_etf_is_left_out_and_foreign_listings_are_summed():
    txns = [
        txn(TxnType.BUY, "2024-01-10", "XFIC.TO", 2000, 100),  # $200,000 of US stocks, Canadian ETF
        txn(TxnType.BUY, "2024-01-10", "FICTUS", 400, 100),  # $40,000
        txn(TxnType.BUY, "2024-01-11", "FICT.L", 300, 100, account=MARGIN),  # $30,000
        txn(TxnType.BUY, "2024-01-12", "FICTCOIN-USD", 1, 90_000),
    ]
    y = year(txns)
    assert [h.symbol for h in y.holdings] == ["FICTUS", "FICT.L"]  # largest first
    assert y.max_cost == pytest.approx(70_000) and y.max_cost_date == "2024-01-11"
    assert y.status == T1135_NOT_REQUIRED


def test_the_setting_overrides_the_listing_both_ways():
    txns = [
        txn(TxnType.BUY, "2024-01-10", "XFIC.TO", 1500, 100),  # $150,000
        txn(TxnType.BUY, "2024-01-10", "FICTUS", 1500, 100),  # $150,000
    ]
    assert [h.symbol for h in year(txns).holdings] == ["FICTUS"]
    swapped = {
        "XFIC.TO": Asset("XFIC.TO", foreign_property=True),  # e.g. a US company listed in Toronto
        "FICTUS": Asset("FICTUS", foreign_property=False),  # e.g. a Canadian company listed in New York
    }
    assert [h.symbol for h in year(txns, assets=swapped).holdings] == ["XFIC.TO"]
    both = {"XFIC.TO": Asset("XFIC.TO", foreign_property=True)}
    assert year(txns, assets=both).max_cost == pytest.approx(300_000)


def test_a_missing_fx_rate_marks_the_year_incomplete():
    def no_usd(day, ccy):
        return 1.0 if ccy == "CAD" else None

    txns = [
        txn(TxnType.BUY, "2024-01-10", "FICT.L", 100, 100),  # $10,000 known
        txn(TxnType.BUY, "2024-02-01", qty=1000, price=100, ccy="USD"),  # US$100,000, rate unknown
    ]
    y = year(txns, fx=no_usd)
    assert y.incomplete and y.max_cost == pytest.approx(10_000)  # what is known; flagged as too low
    assert [(h.symbol, h.incomplete) for h in y.holdings] == [("FICT.L", False), ("FICTUS", True)]


def test_a_sale_missing_its_fx_rate_is_counted_but_its_gain_is_not():
    def no_sale_rate(day, ccy):
        return 1.0 if ccy == "CAD" else (1.3 if day < "2024-06-01" else None)

    txns = [
        txn(TxnType.BUY, "2024-01-10", qty=10, price=100, ccy="USD"),
        txn(TxnType.SELL, "2024-07-10", qty=10, price=150, ccy="USD"),
    ]
    y = year(txns, fx=no_sale_rate)
    (h,) = y.holdings
    assert h.dispositions == 1 and h.gain == 0 and h.incomplete and y.incomplete
    assert y.max_cost == pytest.approx(1_300) and y.year_end_cost == 0


@pytest.mark.parametrize(
    ("cost", "status"),
    [
        (99_999.99, T1135_NOT_REQUIRED),
        (100_000.00, T1135_NOT_REQUIRED),  # the rule is "more than $100,000"
        (100_000.01, T1135_SIMPLIFIED),
        (249_999.99, T1135_SIMPLIFIED),
        (250_000.00, T1135_DETAILED),  # $250,000 or more at any time: the detailed method
        (400_000.00, T1135_DETAILED),
    ],
)
def test_each_status_threshold(cost, status):
    y = year([txn(TxnType.BUY, "2024-04-02", qty=1, price=cost)])
    assert y.max_cost == pytest.approx(cost) and y.status == status


def test_detailed_when_the_peak_lasts_a_single_day():
    txns = [
        txn(TxnType.BUY, "2024-04-02", qty=1000, price=260),  # $260,000 for one day
        txn(TxnType.SELL, "2024-04-03", qty=900, price=260),
    ]
    y = year(txns)
    assert y.status == T1135_DETAILED and y.max_cost_date == "2024-04-02"
    assert y.year_end_cost == pytest.approx(26_000)


def test_same_day_round_trip_counts_only_the_end_of_day_cost():
    txns = [
        txn(TxnType.BUY, "2024-04-02", qty=1000, price=200),
        txn(TxnType.SELL, "2024-04-02", qty=1000, price=201),
    ]
    y = year(txns)
    (h,) = y.holdings
    assert y.max_cost == 0 and y.max_cost_date == "" and h.max_cost_date == ""
    assert h.dispositions == 1 and h.gain == pytest.approx(1_000)


def test_year_in_progress_runs_to_today_and_ignores_later_entries():
    txns = [
        txn(TxnType.BUY, "2024-02-01", qty=100, price=100),
        txn(TxnType.BUY, "2024-09-01", qty=5000, price=100),  # after "today"
    ]
    y = year(txns, today="2024-06-30")
    assert y.as_of == "2024-06-30" and y.max_cost == pytest.approx(10_000)
    assert y.year_end_cost == pytest.approx(10_000)


def test_a_year_before_anything_was_held_is_empty():
    y = year([txn(TxnType.BUY, "2024-02-01", qty=100, price=100)], 2023)
    assert y.holdings == [] and y.max_cost == 0 and y.year_end_cost == 0 and y.max_cost_date == ""
    assert y.status == T1135_NOT_REQUIRED and not y.incomplete and y.gain == 0


def test_every_year_with_foreign_property_newest_first():
    txns = [
        txn(TxnType.BUY, "2021-03-01", "XFIC.TO", 100, 100),  # Canadian: never a year on its own
        txn(TxnType.BUY, "2022-03-01", qty=1000, price=120),  # $120,000
        txn(TxnType.SELL, "2022-11-01", qty=1000, price=130),
        txn(TxnType.BUY, "2024-05-01", "FICT.L", 10, 100),
    ]
    years = foreign_property_years(txns, ACCOUNTS, {}, cad, today="2025-06-30")
    # 2023 held nothing and sold nothing; 2025 still holds the 2024 purchase.
    assert [y.year for y in years] == [2025, 2024, 2022]
    assert years[0].as_of == "2025-06-30" and years[0].max_cost_date == "2025-01-01"
    assert years[2].status == T1135_SIMPLIFIED and years[2].gain == pytest.approx(10_000)
    assert foreign_property_years([txns[0]], ACCOUNTS, {}, cad, today="2025-06-30") == []
    assert foreign_property_years([], ACCOUNTS, {}, cad) == []


# ── The engine's own results don't change ─────────────────────────────────────


def _busy_ledger():
    """Pooling, a superficial loss, a split, return of capital past ACB, transfers both ways
    across the registered line, an unpriced transfer, and USD trades: every path in compute()."""
    return [
        txn(TxnType.BUY, "2024-01-02", "FICTUS", 100, 50, ccy="USD"),
        txn(TxnType.BUY, "2024-01-02", "FICTUS", 50, 60, account=MARGIN, ccy="USD"),
        txn(TxnType.SELL, "2024-02-15", "FICTUS", 80, 40, ccy="USD"),  # a loss…
        txn(TxnType.BUY, "2024-03-01", "FICTUS", 40, 42, ccy="USD"),  # …made superficial
        txn(TxnType.SPLIT, "2024-04-01", "FICTUS", ratio=2),
        txn(TxnType.ROC, "2024-05-01", "FICT.L", amount=9_999),  # nothing held yet: ignored
        txn(TxnType.BUY, "2024-05-02", "FICT.L", 10, 100),
        txn(TxnType.ROC, "2024-06-01", "FICT.L", amount=1_500),  # $500 past ACB: a gain
        txn(TxnType.TRANSFER, "2024-06-15", "FICTUS", 20, 45, ccy="USD", target_account_id=TFSA),
        txn(TxnType.TRANSFER, "2024-07-01", "FICTUS", 10, 47, account=TFSA, ccy="USD", target_account_id=MARGIN),
        txn(TxnType.TRANSFER, "2024-07-02", "FICTUS", 5, 0, account=MARGIN, target_account_id=TAXABLE),
        txn(TxnType.TRANSFER, "2024-08-01", "XFIC.TO", 5, 0, account=RRSP, target_account_id=TAXABLE),
        txn(TxnType.SELL, "2024-12-30", "FICTUS", 30, 70, account=MARGIN, ccy="USD"),
        txn(TxnType.SELL, "2025-01-15", "FICTUS", 1, 70, account=TFSA, ccy="USD"),
    ]


def test_observer_sees_each_ledger_date_once_and_changes_nothing():
    txns = _busy_ledger()
    plain = compute(txns, ACCOUNTS, usd_rates, today="2030-01-01")
    seen: list[str] = []
    watched = compute(txns, ACCOUNTS, usd_rates, today="2030-01-01", on_day=lambda day, pools: seen.append(day))
    assert watched == plain  # dispositions (gains, ACB, superficial losses), open pools and issues
    assert plain.dispositions and plain.issues and any(d.superficial for d in plain.dispositions)
    assert seen == sorted({t.date for t in txns})
    compute([], ACCOUNTS, cad, on_day=lambda day, pools: seen.append("never"))
    assert "never" not in seen


def test_foreign_property_reports_the_same_dispositions_as_compute():
    txns = _busy_ledger()
    report = compute(txns, ACCOUNTS, usd_rates, today="2030-01-01")
    y = foreign_property(txns, ACCOUNTS, {}, usd_rates, 2024, today="2030-01-01")
    expected = {
        symbol: sum(d.allowed_gain for d in report.dispositions if d.symbol == symbol and d.date[:4] == "2024")
        for symbol in ("FICTUS", "FICT.L")
    }
    assert {h.symbol: h.gain for h in y.holdings} == pytest.approx(expected)
