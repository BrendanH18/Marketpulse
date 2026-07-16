"""Money math: average-cost blending, realized P&L, FX conversion, ticker parsing."""

import pytest

from marketpulse.models import FxRates, Portfolio, parse_tickers


def test_buy_opens_position_with_fees_in_cost_base():
    p = Portfolio(name="t")
    pos, blended = p.buy("aapl", 10, 100, fees=10)
    assert not blended
    assert pos.ticker == "AAPL"
    assert pos.shares == 10
    assert pos.avg_cost == pytest.approx(101.0)  # (10*100 + 10) / 10
    assert len(p.transactions) == 1
    assert p.transactions[0].action == "BUY"


def test_buy_blends_average_cost():
    p = Portfolio(name="t")
    p.buy("AAPL", 10, 100)
    pos, blended = p.buy("AAPL", 10, 120)
    assert blended
    assert pos.shares == 20
    assert pos.avg_cost == pytest.approx(110.0)


def test_buy_rejects_nonpositive_shares():
    p = Portfolio(name="t")
    with pytest.raises(ValueError):
        p.buy("AAPL", 0, 100)
    with pytest.raises(ValueError):
        p.buy("AAPL", -5, 100)


def test_sell_realizes_average_cost_gain_and_keeps_avg():
    p = Portfolio(name="t")
    p.buy("AAPL", 10, 100, fees=10)  # avg 101
    realized, pos = p.sell("AAPL", 4, 150, fees=2)
    assert realized == pytest.approx(4 * (150 - 101) - 2)
    assert pos is not None
    assert pos.shares == pytest.approx(6)
    assert pos.avg_cost == pytest.approx(101.0)  # unchanged by the sell


def test_sell_all_closes_position_but_keeps_realized_pnl():
    p = Portfolio(name="t", currency="CAD")
    p.buy("XEQT.TO", 100, 28.50)
    realized, pos = p.sell("XEQT.TO", 100, 30.00)
    assert pos is None
    assert "XEQT.TO" not in p.positions
    assert realized == pytest.approx(150.0)
    assert p.realized_pnl() == {"CAD": pytest.approx(150.0)}


def test_oversell_rejected():
    p = Portfolio(name="t")
    p.buy("AAPL", 10, 100)
    with pytest.raises(ValueError):
        p.sell("AAPL", 11, 100)
    # nothing recorded for the failed sell
    assert len(p.transactions) == 1
    assert p.positions["AAPL"].shares == 10


def test_sell_unknown_ticker_rejected():
    p = Portfolio(name="t")
    with pytest.raises(ValueError):
        p.sell("AAPL", 1, 100)


def test_realized_pnl_replays_ledger_per_currency():
    p = Portfolio(name="t", currency="CAD")
    p.buy("AAPL", 10, 100, currency="USD")
    p.buy("AAPL", 10, 120, currency="USD")  # avg 110
    p.sell("AAPL", 5, 130, fees=5)  # +5*20 - 5 = 95 USD
    p.buy("XEQT.TO", 50, 28)  # no currency -> folds to CAD
    p.sell("XEQT.TO", 10, 30)  # +20 CAD
    pnl = p.realized_pnl()
    assert pnl["USD"] == pytest.approx(95.0)
    assert pnl["CAD"] == pytest.approx(20.0)


def test_add_position_is_buy_alias_and_records_transaction():
    p = Portfolio(name="t")
    pos, blended = p.add_position("aapl", 10, 100, note="legacy path")
    assert not blended
    assert pos.avg_cost == pytest.approx(100.0)
    assert len(p.transactions) == 1
    assert p.transactions[0].note == "legacy path"


def test_fx_rates_identity_and_missing():
    fx = FxRates(base="CAD", rates={"CAD": 1.0, "USD": 1.35})
    assert fx.rate("CAD") == 1.0
    assert fx.rate("") == 1.0  # unknown currency assumed base
    assert fx.rate("USD") == 1.35
    assert fx.rate("EUR") is None
    assert fx.convert(100, "USD") == pytest.approx(135.0)
    assert fx.convert(100, "EUR") is None


def test_parse_tickers_dedupes_and_uppercases():
    assert parse_tickers("aapl, msft AAPL  xeqt.to") == ["AAPL", "MSFT", "XEQT.TO"]
    assert parse_tickers("") == []
