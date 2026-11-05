"""The fallback quote provider path in `MarketData`, with a stub provider (fictional prices)."""

from __future__ import annotations

import json
import time

import pytest

from marketpulse.automation import run_cycle
from marketpulse.market import FALLBACK_AFTER, FALLBACK_META, STATUS_META, MarketData, MarketError
from marketpulse.models import Quote, Transaction, TxnType


class StubProvider:
    name = "stub"
    label = "Stub Quotes"
    batch_limit = 2
    min_interval = 900.0
    daily_limit = 5

    def __init__(self, prices: dict[str, float] | None = None, error: str | None = None):
        self.prices = prices or {}
        self.error = error
        self.calls: list[list[str]] = []

    def quotes(self, symbols):
        self.calls.append(list(symbols))
        if self.error:
            raise MarketError(self.error)
        out = {
            s: Quote(symbol=s, price=p, prev_close=p, currency="CAD", market_time=time.time(), fetched_at=time.time())
            for s, p in self.prices.items()
            if s in symbols
        }
        return out, {s: "symbol not found" for s in symbols if s not in out}


def test_fallback_is_not_asked_while_yahoo_answers(fake, store):
    stub = StubProvider({"AAPL": 1.0})
    quotes, errors = MarketData(fake, store, stub).quotes(["AAPL", "NOPE"])
    assert quotes["AAPL"].source == "yahoo" and quotes["AAPL"].price == 200
    assert errors == {"NOPE": "symbol not found"}  # unknown to Yahoo is not an outage
    assert stub.calls == []


def age_cache(store, symbol, seconds):
    q = store.cached_quotes([symbol])[symbol]
    q.fetched_at -= seconds
    q.market_time = (q.market_time or time.time()) - seconds
    store.cache_quotes([q])


def test_fallback_answers_when_yahoo_is_down(fake, store):
    MarketData(fake, store).quotes(["AAPL", "XEQT.TO"])  # cache both
    age_cache(store, "XEQT.TO", FALLBACK_AFTER + 60)
    fake.offline = True
    stub = StubProvider({"XEQT.TO": 41.0, "AAPL": 1.0})
    quotes, errors = MarketData(fake, store, stub).quotes(["AAPL", "XEQT.TO", "SHOP.TO"])
    # A recent cached price is good enough; the fallback's few calls go to what's missing or old.
    assert stub.calls == [["SHOP.TO", "XEQT.TO"]]
    fresh = quotes["XEQT.TO"]
    assert (fresh.price, fresh.source, fresh.stale) == (41.0, "stub", False)
    assert fresh.name == "iShares Core Equity ETF Portfolio" and fresh.instrument_type == "ETF"  # kept from Yahoo
    assert quotes["AAPL"].stale and quotes["AAPL"].source == "yahoo"
    assert "offline" in errors["SHOP.TO"] and set(errors) == {"SHOP.TO"}
    # The fallback quote is cached like any other, with its source.
    assert store.cached_quotes(["XEQT.TO"])["XEQT.TO"].source == "stub"


def test_fallback_never_replaces_a_newer_cached_price(fake, store):
    MarketData(fake, store).quotes(["XEQT.TO"])
    age_cache(store, "XEQT.TO", FALLBACK_AFTER + 60)
    fake.offline = True

    class PreviousClose(StubProvider):
        def quotes(self, symbols):
            out, errors = super().quotes(symbols)
            for q in out.values():
                q.market_time = time.time() - 3 * 86400  # older than Yahoo's last trade
            return out, errors

    stub = PreviousClose({"XEQT.TO": 39.0})
    quotes, _ = MarketData(fake, store, stub).quotes(["XEQT.TO"])
    assert stub.calls and quotes["XEQT.TO"].stale and quotes["XEQT.TO"].price == 40.0


def test_fallback_keeps_to_its_interval_batch_and_daily_limit(fake, store):
    fake.offline = True
    stub = StubProvider({})
    symbols = ["A1", "A2", "A3", "A4", "A5", "A6", "A7"]
    MarketData(fake, store, stub).quotes(symbols, use_cache=False)
    # Another process (a fresh MarketData on the same database) within the interval waits.
    MarketData(fake, store, stub).quotes(symbols, use_cache=False)
    assert stub.calls == [["A1", "A2"]]
    for _ in range(3):
        state = json.loads(store.get_meta(FALLBACK_META))
        store.set_meta(FALLBACK_META, json.dumps({**state, "last": 0}))
        MarketData(fake, store, stub).quotes(symbols, use_cache=False)
    # Two per attempt, five a day: the third attempt gets one, the fourth none.
    assert [len(c) for c in stub.calls] == [2, 2, 1]


def test_provider_status_records_each_attempt(fake, store):
    stub = StubProvider(error="Stub Quotes returned HTTP 429")
    md = MarketData(fake, store, stub)
    md.quotes(["AAPL"])
    age_cache(store, "AAPL", FALLBACK_AFTER + 60)
    yahoo, fallback = md.provider_status()
    assert (yahoo.name, yahoo.role, yahoo.ok, yahoo.quotes, yahoo.last_error) == ("yahoo", "primary", True, 1, None)
    assert (fallback.name, fallback.role, fallback.ok) == ("stub", "fallback", None)

    fake.offline = True
    md.quotes(["AAPL"], use_cache=False)
    yahoo, fallback = MarketData(fake, store, stub).provider_status()  # read back by another process
    assert yahoo.ok is False and "offline" in yahoo.last_error and yahoo.last_success is not None
    assert fallback.ok is False and fallback.last_error == "Stub Quotes returned HTTP 429"
    assert fallback.last_success is None


def test_provider_status_without_fallback_or_history(store):
    (yahoo,) = MarketData(store=store).provider_status()
    assert (yahoo.name, yahoo.ok, yahoo.last_attempt) == ("yahoo", None, None)
    store.set_meta(STATUS_META, "not json")
    assert MarketData(store=store).provider_status()[0].ok is None


def test_fx_falls_back_too(fake, store):
    fake.offline = True
    stub = StubProvider({"USDCAD=X": 1.4})
    fx, errors = MarketData(fake, store, stub).fx_rates(["USD"], "CAD")
    assert fx.rate("USD") == 1.4 and not fx.stale and errors == {}


def test_cycle_reports_stale_count_and_age(tracker, fake):
    acct = tracker.store.ensure_default_account("CAD")
    tracker.store.add_transaction(
        Transaction(acct.saved_id, TxnType.BUY, "2024-01-02", "AAPL", 2, 150.0, currency="USD")
    )
    tracker.valuation(record=False)
    fetched = tracker.store.cached_quotes(["AAPL"])["AAPL"].fetched_at
    fake.offline = True
    report = run_cycle(tracker, fresh=True).report
    assert report["stale"] is True and report["stale_count"] == 1  # prices; FX shows in `stale`
    assert report["stale_since"] is not None
    assert report["stale_since"] <= time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(fetched + 1))
    saved = json.loads(tracker.store.get_meta("automation_last_run"))
    assert saved["stale_count"] == 1


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(None, "unknown age"), (-3, "0 s"), (59, "59 s"), (60, "1 min"), (7199, "1 h"), (90000, "1 d")],
)
def test_age_text(seconds, text):
    from marketpulse import fmt

    assert fmt.age(seconds) == text


def test_two_processes_cannot_both_spend_the_budget(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from marketpulse.db import Store

    path = tmp_path / "shared.db"
    stores = [Store(path), Store(path)]  # separate connections, as two processes have
    barrier = Barrier(2)

    def grab(store):
        md = MarketData(store=store, fallback=StubProvider())
        barrier.wait()
        return md._fallback_budget(5)

    try:
        for _ in range(20):
            stores[0].set_meta(FALLBACK_META, "{}")
            with ThreadPoolExecutor(2) as pool:
                grants = sorted(pool.map(grab, stores))
            assert grants == [0, StubProvider.batch_limit]
            assert json.loads(stores[0].get_meta(FALLBACK_META))["used"] == StubProvider.batch_limit
    finally:
        for s in stores:
            s.close()
