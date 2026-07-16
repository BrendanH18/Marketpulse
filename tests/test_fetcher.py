"""Fetch layer: retry/backoff, TTL caching, FX rates, error contract."""

import pytest
from conftest import FakeTicker, make_fast_info

from marketpulse import fetcher


def test_retry_recovers_after_transient_failures(ticker_factory, no_sleep):
    attempts = {"n": 0}

    def make(symbol):
        attempts["n"] += 1
        if attempts["n"] < 3:
            return FakeTicker(exc=ConnectionError("transient"))
        return FakeTicker(fast_info=make_fast_info(price=123.0), info={"longName": "Test Corp"})

    ticker_factory(make)
    quote = fetcher.fetch_quote("TST")
    assert quote.price == 123.0
    assert quote.name == "Test Corp"
    assert attempts["n"] == 3  # failed twice, succeeded on the final attempt


def test_permanent_failure_raises_runtime_error_after_all_attempts(ticker_factory, no_sleep):
    calls = ticker_factory(lambda s: FakeTicker(exc=ConnectionError("down")))
    with pytest.raises(RuntimeError, match="Failed to fetch TST"):
        fetcher.fetch_quote("TST")
    assert len(calls) == fetcher.RETRY_ATTEMPTS


def test_quote_cache_hit_skips_network(ticker_factory):
    calls = ticker_factory(lambda s: FakeTicker(fast_info=make_fast_info(), info={"longName": "Cached"}))
    q1 = fetcher.fetch_quote("AAPL")
    q2 = fetcher.fetch_quote("aapl")  # case-insensitive key
    assert q1 is q2
    assert len(calls) == 1


def test_quote_cache_expiry_refetches(ticker_factory, monkeypatch):
    calls = ticker_factory(lambda s: FakeTicker(fast_info=make_fast_info(), info={"longName": "X"}))
    monkeypatch.setattr(fetcher, "QUOTE_TTL", 0.0)
    fetcher.fetch_quote("AAPL")
    fetcher.fetch_quote("AAPL")
    assert len(calls) == 2


def test_cache_bypass_with_use_cache_false(ticker_factory):
    calls = ticker_factory(lambda s: FakeTicker(fast_info=make_fast_info(), info={"longName": "X"}))
    fetcher.fetch_quote("AAPL")
    fetcher.fetch_quote("AAPL", use_cache=False)
    assert len(calls) == 2


def test_fetch_quotes_partitions_successes_and_failures(ticker_factory, no_sleep):
    def make(symbol):
        if symbol == "BAD":
            return FakeTicker(exc=ConnectionError("nope"))
        return FakeTicker(fast_info=make_fast_info(price=50.0), info={"longName": symbol})

    ticker_factory(make)
    quotes, errors = fetcher.fetch_quotes(["good", "BAD"])
    assert set(quotes) == {"GOOD"}
    assert set(errors) == {"BAD"}
    assert "Failed to fetch BAD" in errors["BAD"]


def test_missing_price_is_an_error_not_a_zero(ticker_factory, no_sleep):
    ticker_factory(lambda s: FakeTicker(fast_info=make_fast_info(last_price=None), info={}))
    with pytest.raises(RuntimeError, match="no price data"):
        fetcher.fetch_quote("GHOST")


def test_fx_rate_identity_needs_no_network(ticker_factory):
    calls = ticker_factory(lambda s: FakeTicker(exc=AssertionError("network hit")))
    assert fetcher.fetch_fx_rate("CAD", "CAD") == 1.0
    assert fetcher.fetch_fx_rate("", "CAD") == 1.0
    assert calls == []


def test_fx_rate_uses_pair_ticker_and_caches(ticker_factory):
    calls = ticker_factory(lambda s: FakeTicker(fast_info=make_fast_info(last_price=1.35)))
    rate = fetcher.fetch_fx_rate("usd", "cad")
    assert rate == pytest.approx(1.35)
    assert calls == ["USDCAD=X"]
    fetcher.fetch_fx_rate("USD", "CAD")  # cached
    assert len(calls) == 1


def test_fetch_fx_rates_reports_failures_separately(ticker_factory, no_sleep):
    def make(symbol):
        if symbol.startswith("EUR"):
            return FakeTicker(exc=ConnectionError("down"))
        return FakeTicker(fast_info=make_fast_info(last_price=1.35))

    ticker_factory(make)
    fx, errors = fetcher.fetch_fx_rates(["USD", "EUR", "CAD"], "CAD")
    assert fx.base == "CAD"
    assert fx.rate("CAD") == 1.0
    assert fx.rate("USD") == pytest.approx(1.35)
    assert fx.rate("EUR") is None
    assert set(errors) == {"EUR"}
