"""Shared fixtures: isolated data dir, cleared fetch caches, fake yfinance."""

import pytest

from marketpulse import fetcher


@pytest.fixture(autouse=True)
def _clear_caches():
    fetcher.clear_caches()
    yield
    fetcher.clear_caches()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point MARKETPULSE_DATA at a temp dir so tests never touch ~/.marketpulse."""
    monkeypatch.setenv("MARKETPULSE_DATA", str(tmp_path))
    return tmp_path


@pytest.fixture
def no_sleep(monkeypatch):
    """Disable retry backoff delays."""
    monkeypatch.setattr(fetcher.time, "sleep", lambda _s: None)


class FakeFastInfo:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeTicker:
    """Stands in for yf.Ticker: configurable fast_info, info, and failures."""

    def __init__(self, fast_info=None, info=None, exc: Exception | None = None):
        self._fast_info = fast_info
        self._info = info or {}
        self._exc = exc

    @property
    def fast_info(self):
        if self._exc is not None:
            raise self._exc
        return self._fast_info

    @property
    def info(self):
        return self._info


def make_fast_info(price: float = 100.0, currency: str = "USD", **overrides) -> FakeFastInfo:
    defaults = dict(
        last_price=price,
        previous_close=price - 1,
        day_high=price + 2,
        day_low=price - 2,
        last_volume=1000,
        market_cap=1e9,
        currency=currency,
        exchange="TEST",
        fifty_two_week_high=price + 10,
        fifty_two_week_low=price - 10,
    )
    defaults.update(overrides)
    return FakeFastInfo(**defaults)


@pytest.fixture
def ticker_factory(monkeypatch):
    """Replace fetcher.yf.Ticker with a factory; returns the list of symbols requested."""

    def install(make_ticker):
        calls: list[str] = []

        def factory(symbol: str):
            calls.append(symbol)
            return make_ticker(symbol)

        monkeypatch.setattr(fetcher.yf, "Ticker", factory)
        return calls

    return install
