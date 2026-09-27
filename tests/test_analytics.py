from datetime import date

import pytest

from marketpulse.analytics import (
    external_flows,
    income_by_month,
    max_drawdown,
    period_return,
    rebalance,
    twr_index,
    volatility,
    xirr,
)
from marketpulse.ledger import replay
from marketpulse.models import Account, Transaction, TxnType
from marketpulse.valuation import Breakdown


def test_xirr_one_year_ten_percent():
    assert xirr([("2023-01-01", -1000), ("2024-01-01", 1100)]) == pytest.approx(10.0, abs=0.05)


def test_xirr_requires_in_and_out():
    assert xirr([("2023-01-01", -1000)]) is None
    assert xirr([("2023-01-01", -1000), ("2023-01-01", 1000)]) is None


def test_twr_strips_out_contributions():
    idx = twr_index([("d1", 100, 100), ("d2", 110, 100), ("d3", 220, 200)])
    assert idx[-1][1] == pytest.approx(1.1 * (120 / 110))


def test_drawdown_volatility_and_period_return():
    assert max_drawdown([100, 120, 90, 130]) == pytest.approx(-25)
    assert volatility([100, 101]) is None
    assert volatility([100 + (i % 2) for i in range(30)]) > 0
    assert period_return([50, 75]) == pytest.approx(50)
    assert period_return([5]) is None


def test_external_flows_by_account_style():
    accounts = {1: Account(name="Invested", id=1), 2: Account(name="Cash", id=2)}
    txns = [
        Transaction(
            account_id=1, type=TxnType.BUY, date="2024-01-01", symbol="A", quantity=10, price=10, fees=1, currency="CAD"
        ),
        Transaction(
            account_id=1, type=TxnType.SELL, date="2024-02-01", symbol="A", quantity=5, price=12, fees=1, currency="CAD"
        ),
        Transaction(account_id=1, type=TxnType.DIVIDEND, date="2024-03-01", symbol="A", amount=3, currency="CAD"),
        Transaction(account_id=2, type=TxnType.DEPOSIT, date="2024-01-01", amount=500, currency="CAD"),
        Transaction(
            account_id=2, type=TxnType.BUY, date="2024-01-02", symbol="B", quantity=1, price=100, currency="CAD"
        ),
    ]
    assert [a for _, a, _ in external_flows(txns, accounts)] == [101, 500, -59, -3]


def test_rebalance_suggests_trades():
    rows = rebalance([Breakdown("etf", "ETF", 80), Breakdown("cash", "Cash", 20)], {"etf": 60, "fixed_income": 40}, 100)
    deltas = {r.bucket: round(r.delta) for r in rows}
    assert deltas == {"etf": -20, "fixed_income": 40, "cash": -20}
    assert rows[0].bucket == "fixed_income"


def test_income_by_month_buckets():
    accounts = {1: Account(name="A", id=1)}
    txns = [Transaction(account_id=1, type=TxnType.DIVIDEND, date="2026-03-15", symbol="X", amount=12, currency="CAD")]
    months = income_by_month(replay(txns, accounts), lambda a, c: a, today=date(2026, 9, 14))
    assert len(months) == 12
    assert dict(months)["2026-03"] == 12
    assert months[-1][0] == "2026-09"
