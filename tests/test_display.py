"""Display math: multi-currency portfolio totals never mix currencies silently."""

import pytest

from marketpulse.display import _portfolio_totals
from marketpulse.models import FxRates, Portfolio, Quote


def _quote(ticker: str, price: float, prev_close: float, currency: str) -> Quote:
    return Quote(
        ticker=ticker,
        name=ticker,
        price=price,
        prev_close=prev_close,
        day_high=price,
        day_low=price,
        volume=0,
        market_cap=None,
        currency=currency,
        exchange="TEST",
    )


def _mixed_portfolio() -> Portfolio:
    p = Portfolio(name="t", currency="CAD")
    p.buy("AAPL", 10, 100, currency="USD")
    p.buy("XEQT.TO", 100, 28, currency="CAD")
    return p


QUOTES = {
    "AAPL": _quote("AAPL", 150.0, 148.0, "USD"),
    "XEQT.TO": _quote("XEQT.TO", 30.0, 29.5, "CAD"),
}


def test_totals_convert_to_base_currency():
    fx = FxRates(base="CAD", rates={"CAD": 1.0, "USD": 1.35})
    totals = _portfolio_totals(_mixed_portfolio(), QUOTES, fx)
    assert totals.market == pytest.approx(10 * 150 * 1.35 + 100 * 30)
    assert totals.book == pytest.approx(10 * 100 * 1.35 + 100 * 28)
    assert totals.day == pytest.approx(10 * 2 * 1.35 + 100 * 0.5)
    assert totals.missing_quotes == []
    assert totals.missing_fx == []


def test_position_without_fx_rate_is_excluded_and_reported():
    fx = FxRates(base="CAD", rates={"CAD": 1.0})  # no USD rate
    totals = _portfolio_totals(_mixed_portfolio(), QUOTES, fx)
    assert totals.missing_fx == ["AAPL"]
    assert totals.market == pytest.approx(100 * 30)  # CAD position only
    assert totals.book == pytest.approx(100 * 28)


def test_position_without_quote_is_excluded_and_reported():
    fx = FxRates(base="CAD", rates={"CAD": 1.0, "USD": 1.35})
    quotes = {"XEQT.TO": QUOTES["XEQT.TO"]}  # AAPL fetch failed
    totals = _portfolio_totals(_mixed_portfolio(), quotes, fx)
    assert totals.missing_quotes == ["AAPL"]
    assert totals.market == pytest.approx(100 * 30)


def test_legacy_position_falls_back_to_quote_currency():
    p = Portfolio(name="t", currency="CAD")
    p.buy("AAPL", 10, 100)  # no currency recorded (legacy/TUI path)
    fx = FxRates(base="CAD", rates={"CAD": 1.0, "USD": 1.35})
    totals = _portfolio_totals(p, {"AAPL": QUOTES["AAPL"]}, fx)
    # quote says USD, so the position is converted, not summed raw
    assert totals.market == pytest.approx(10 * 150 * 1.35)
