import pytest

from marketpulse.market import SPARK_URL, MarketData, MarketError, _market_state, quote_from_meta


def spark_calls(fake):
    return [params for url, params in fake.calls if url == SPARK_URL]


def test_batch_quotes_parse_and_report_missing(market):
    quotes, errors = market.quotes(["aapl", "XEQT.TO", "NOPE"])
    q = quotes["AAPL"]
    assert (q.price, q.prev_close, q.currency, q.name) == (200, 190, "USD", "Apple Inc.")
    assert q.change_pct == pytest.approx(5.263, rel=1e-3)
    assert q.intraday == [190, 200]
    assert quotes["XEQT.TO"].asset_class.value == "etf"
    assert errors == {"NOPE": "symbol not found"}


def test_quotes_are_chunked_to_twenty(fake):
    symbols = [f"S{i}" for i in range(45)]
    for i, s in enumerate(symbols):
        fake.set_quote(s, 10 + i)
    quotes, errors = MarketData(fake).quotes(symbols)
    calls = spark_calls(fake)
    assert len(quotes) == 45 and not errors
    assert len(calls) == 3 and max(len(c["symbols"].split(",")) for c in calls) == 20


def test_quote_cache(market, fake):
    market.quotes(["AAPL"])
    market.quotes(["AAPL"])
    assert len(spark_calls(fake)) == 1
    market.quotes(["AAPL"], use_cache=False)
    assert len(spark_calls(fake)) == 2


def test_offline_uses_last_known_quotes(store, fake):
    MarketData(fake, store).quotes(["AAPL"])
    fake.offline = True
    quotes, errors = MarketData(fake, store).quotes(["AAPL", "XEQT.TO"])
    assert quotes["AAPL"].stale and quotes["AAPL"].price == 200
    assert "offline" in errors["XEQT.TO"]


def test_quote_errors_raise(market):
    with pytest.raises(MarketError, match="NOPE"):
        market.quote("NOPE")


def test_minor_currency_units_are_normalized():
    q = quote_from_meta(
        {"symbol": "VOD.L", "regularMarketPrice": 7250, "previousClose": 7200, "currency": "GBp"}, [7200, 7250]
    )
    assert (q.currency, q.price, q.prev_close, q.intraday) == ("GBP", 72.5, 72.0, [72.0, 72.5])
    assert quote_from_meta({"symbol": "X"}) is None


def test_history_daily_closes_and_errors(market, fake):
    fake.set_history("AAPL", {"2024-01-02": 1.0, "2024-01-03": 2.0})
    bars = market.history("AAPL", "1mo")
    assert [b.close for b in bars] == [1.0, 2.0] and bars[0].date == "2024-01-02"
    closes, ccy = market.daily_closes("AAPL", "2024-01-01")
    assert closes == {"2024-01-02": 1.0, "2024-01-03": 2.0} and ccy == "USD"
    with pytest.raises(MarketError, match="No data"):
        market.history("ZZZ", "1mo")
    with pytest.raises(MarketError, match="Unknown period"):
        market.history("AAPL", "3w")


def test_dividends(market, fake):
    fake.set_history("AAPL", {"2024-01-02": 1.0})
    fake.dividends["AAPL"] = [("2024-02-09", 0.24), ("2024-01-02", 0.25)]
    assert market.dividends("AAPL") == [("2024-01-02", 0.25), ("2024-02-09", 0.24)]


def test_search(market, fake):
    fake.search_results = [
        {"symbol": "enb.to", "longname": "Enbridge Inc.", "exchDisp": "Toronto", "typeDisp": "Equity"},
        {"name": "no symbol"},
    ]
    results = market.search("enbridge")
    assert [(r.symbol, r.name, r.exchange) for r in results] == [("ENB.TO", "Enbridge Inc.", "Toronto")]
    assert market.search("   ") == []


def test_fx_rates(market):
    fx, errors = market.fx_rates(["USD", "CAD", "EUR", ""], "cad")
    assert fx.base == "CAD" and fx.rate("USD") == 1.35
    assert set(errors) == {"EUR"}


def test_market_state():
    periods = {"currentTradingPeriod": {"pre": {"start": 50, "end": 100}, "regular": {"start": 100, "end": 200}}}
    assert _market_state(periods, now=150) == "REGULAR"
    assert _market_state(periods, now=60) == "PRE"
    assert _market_state(periods, now=250) == "CLOSED"
    assert _market_state({"instrumentType": "CRYPTOCURRENCY"}) == "REGULAR"
    assert _market_state({}) == ""
