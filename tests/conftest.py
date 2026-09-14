"""Shared fixtures: isolated paths, a fake Yahoo transport, and a wired Tracker."""

from __future__ import annotations

from datetime import date, datetime
from urllib.parse import unquote

import pytest

from marketpulse import themes
from marketpulse.config import Config
from marketpulse.db import Store
from marketpulse.market import CHART_URL, SEARCH_URL, SPARK_URL, MarketData, MarketError
from marketpulse.services import Tracker

CHART_PREFIX = CHART_URL.split("{")[0]


def noon(day: str) -> int:
    return int(datetime.combine(date.fromisoformat(day), datetime.min.time()).replace(hour=12).timestamp())


class FakeTransport:
    """Speaks just enough of Yahoo's spark/chart/search JSON for the app."""

    def __init__(self) -> None:
        self.quotes: dict[str, dict] = {}
        self.history: dict[str, dict] = {}
        self.dividends: dict[str, list[tuple[str, float]]] = {}
        self.search_results: list[dict] = []
        self.offline = False
        self.calls: list[tuple[str, dict]] = []

    def set_quote(self, symbol, price, prev=None, currency="USD", name=None, instrument="EQUITY"):
        self.quotes[symbol] = {
            "price": price,
            "prev": price if prev is None else prev,
            "currency": currency,
            "name": name or symbol,
            "type": instrument,
        }

    def set_history(self, symbol, closes: dict[str, float], currency="USD"):
        self.history[symbol] = {"closes": closes, "currency": currency}

    def get_json(self, url, params):
        self.calls.append((url, dict(params)))
        if self.offline:
            raise MarketError("network error: offline")
        if url == SPARK_URL:
            result = []
            for sym in params["symbols"].split(","):
                q = self.quotes.get(sym)
                if q is None:
                    continue
                meta = {
                    "symbol": sym,
                    "regularMarketPrice": q["price"],
                    "previousClose": q["prev"],
                    "currency": q["currency"],
                    "longName": q["name"],
                    "instrumentType": q["type"],
                    "fiftyTwoWeekHigh": q["price"] * 1.2,
                    "fiftyTwoWeekLow": q["price"] * 0.8,
                    "regularMarketVolume": 1000,
                }
                closes = [q["prev"], None, q["price"]]
                result.append(
                    {"symbol": sym, "response": [{"meta": meta, "indicators": {"quote": [{"close": closes}]}}]}
                )
            return {"spark": {"result": result, "error": None}}
        if url.startswith(CHART_PREFIX):
            sym = unquote(url[len(CHART_PREFIX) :])
            h = self.history.get(sym)
            if h is None:
                return {"chart": {"result": None, "error": {"code": "Not Found", "description": "No data found"}}}
            days = sorted(h["closes"])
            closes = [h["closes"][d] for d in days]
            divs = {str(noon(d)): {"amount": a, "date": noon(d)} for d, a in self.dividends.get(sym, [])}
            quote = {"open": closes, "high": closes, "low": closes, "close": closes, "volume": [100] * len(closes)}
            return {
                "chart": {
                    "result": [
                        {
                            "meta": {"symbol": sym, "currency": h["currency"]},
                            "timestamp": [noon(d) for d in days],
                            "indicators": {"quote": [quote]},
                            "events": {"dividends": divs},
                        }
                    ],
                    "error": None,
                }
            }
        if url == SEARCH_URL:
            return {"quotes": self.search_results}
        raise AssertionError(f"unexpected URL {url}")


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Never touch ~/.marketpulse, the real config, a real Omarchy install or Notification Center."""
    monkeypatch.setenv("MARKETPULSE_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("MARKETPULSE_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setattr(themes, "omarchy_active", lambda dirs=None: None)


@pytest.fixture(autouse=True)
def notifications(monkeypatch):
    sent: list[tuple] = []
    monkeypatch.setattr("marketpulse.alerts.notify", lambda *args, **kwargs: sent.append(args) or True)
    return sent


@pytest.fixture
def fake() -> FakeTransport:
    t = FakeTransport()
    t.set_quote("AAPL", 200.0, 190.0, "USD", "Apple Inc.")
    t.set_quote("XEQT.TO", 40.0, 40.5, "CAD", "iShares Core Equity ETF Portfolio", "ETF")
    t.set_quote("USDCAD=X", 1.35, 1.34, "CAD", "USD/CAD", "CURRENCY")
    return t


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "test.db")
    yield s
    s.close()


@pytest.fixture
def market(fake, store) -> MarketData:
    return MarketData(transport=fake, store=store)


@pytest.fixture
def tracker(store, market) -> Tracker:
    return Tracker(store, market, Config())
