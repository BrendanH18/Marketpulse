"""Market data fetching via yfinance."""

import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypeVar

import yfinance as yf

from .models import FxRates, Quote

if TYPE_CHECKING:
    import pandas as pd

T = TypeVar("T")

# yfinance is flaky: transient HTTP errors and empty payloads are common,
# so every network call is retried with a short backoff.
RETRY_ATTEMPTS = 3
RETRY_BASE_DELAY = 0.5  # seconds; doubles each attempt

# Short TTL caches so a burst of refreshes (e.g. the TUI's watchlist and
# portfolio workers requesting the same tickers) hits the network once.
QUOTE_TTL = 15.0
FX_TTL = 300.0

_cache_lock = threading.Lock()
_quote_cache: dict[str, tuple[Quote, float]] = {}
_fx_cache: dict[tuple[str, str], tuple[float, float]] = {}


def clear_caches() -> None:
    with _cache_lock:
        _quote_cache.clear()
        _fx_cache.clear()


def _cache_get(cache: dict, key) -> Any:
    with _cache_lock:
        entry = cache.get(key)
        if entry is None:
            return None
        value, expiry = entry
        if time.monotonic() >= expiry:
            del cache[key]
            return None
        return value


def _cache_put(cache: dict, key, value, ttl: float) -> None:
    with _cache_lock:
        cache[key] = (value, time.monotonic() + ttl)


def _with_retry(fn: Callable[[], T], attempts: int = RETRY_ATTEMPTS, base_delay: float = RETRY_BASE_DELAY) -> T:
    last_exc: Exception = RuntimeError("no attempts made")
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < attempts - 1:
                time.sleep(base_delay * (2**attempt))
    raise last_exc


def _fetch_quote_once(ticker: str) -> Quote:
    t = yf.Ticker(ticker)
    info = t.fast_info

    # fast_info gives us what we need without heavy API calls
    price = getattr(info, "last_price", None) or getattr(info, "regularMarketPrice", None)
    prev_close = getattr(info, "previous_close", None) or getattr(info, "regularMarketPreviousClose", None)
    day_high = getattr(info, "day_high", None) or 0.0
    day_low = getattr(info, "day_low", None) or 0.0
    volume = getattr(info, "last_volume", None) or 0
    market_cap = getattr(info, "market_cap", None)
    currency = getattr(info, "currency", "USD") or "USD"
    exchange = getattr(info, "exchange", "?") or "?"
    week52_high = getattr(info, "fifty_two_week_high", None)
    week52_low = getattr(info, "fifty_two_week_low", None)

    # Fall back to slower info if fast_info is missing price
    if price is None:
        full_info = t.info
        price = full_info.get("currentPrice") or full_info.get("regularMarketPrice")
        prev_close = full_info.get("previousClose") or full_info.get("regularMarketPreviousClose", price)
        day_high = full_info.get("dayHigh", 0.0)
        day_low = full_info.get("dayLow", 0.0)
        volume = full_info.get("volume", 0)
        market_cap = full_info.get("marketCap")
        currency = full_info.get("currency", "USD")
        exchange = full_info.get("exchange", "?")
        name = full_info.get("longName") or full_info.get("shortName") or ticker
    else:
        try:
            full_info = t.info
            name = full_info.get("longName") or full_info.get("shortName") or ticker
        except Exception:
            name = ticker

    # yfinance returns empty data instead of raising for unknown tickers
    if not price:
        raise ValueError("no price data (invalid or delisted ticker?)")

    return Quote(
        ticker=ticker.upper(),
        name=name,
        price=float(price),
        prev_close=float(prev_close or price or 0),
        day_high=float(day_high or 0),
        day_low=float(day_low or 0),
        volume=int(volume or 0),
        market_cap=float(market_cap) if market_cap else None,
        currency=currency,
        exchange=exchange,
        week52_high=float(week52_high) if week52_high else None,
        week52_low=float(week52_low) if week52_low else None,
        timestamp=datetime.now(),
    )


def fetch_quote(ticker: str, *, use_cache: bool = True) -> Quote:
    """Fetch a single live quote for a ticker (retried, briefly cached)."""
    key = ticker.upper()
    if use_cache:
        cached = _cache_get(_quote_cache, key)
        if cached is not None:
            return cached
    try:
        quote = _with_retry(lambda: _fetch_quote_once(ticker))
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {ticker}: {e}") from e
    _cache_put(_quote_cache, key, quote, QUOTE_TTL)
    return quote


def fetch_quotes(tickers: list[str], *, use_cache: bool = True) -> tuple[dict[str, Quote], dict[str, str]]:
    """Fetch quotes for multiple tickers in parallel.

    Returns (quotes, errors): quotes keyed by upper-cased ticker, and an
    error-message dict for every ticker that failed.
    """
    if not tickers:
        return {}, {}
    results = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 10)) as executor:
        futures = {executor.submit(fetch_quote, ticker, use_cache=use_cache): ticker for ticker in tickers}
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                quote = future.result()
                results[quote.ticker] = quote
            except RuntimeError as e:
                errors[ticker.upper()] = str(e)
    return results, errors


def fetch_history(ticker: str, period: str = "1mo") -> "pd.DataFrame":
    """Fetch OHLCV history. period: 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y."""

    def _once():
        hist = yf.Ticker(ticker).history(period=period)
        return hist

    try:
        return _with_retry(_once)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch history for {ticker}: {e}") from e


def fetch_fx_rate(currency: str, base: str) -> float:
    """Fetch the spot rate converting `currency` into `base` (e.g. USD->CAD).

    Uses yfinance currency-pair tickers like USDCAD=X. Retried and cached.
    Raises RuntimeError on failure.
    """
    currency = currency.upper()
    base = base.upper()
    if not currency or currency == base:
        return 1.0
    key = (currency, base)
    cached = _cache_get(_fx_cache, key)
    if cached is not None:
        return cached

    pair = f"{currency}{base}=X"

    def _once() -> float:
        info = yf.Ticker(pair).fast_info
        rate = getattr(info, "last_price", None)
        if not rate:
            raise ValueError(f"no rate data for {pair}")
        return float(rate)

    try:
        rate = _with_retry(_once)
    except Exception as e:
        raise RuntimeError(f"Failed to fetch FX rate {currency}->{base}: {e}") from e
    _cache_put(_fx_cache, key, rate, FX_TTL)
    return rate


def fetch_fx_rates(currencies: Iterable[str], base: str) -> tuple[FxRates, dict[str, str]]:
    """Fetch rates for every currency into `base`, in parallel.

    Returns (FxRates, errors). FxRates contains every rate that succeeded
    (the base itself is always present at 1.0); errors maps currency -> reason
    so callers can surface positions excluded from converted totals.
    """
    base = base.upper()
    wanted = {c.upper() for c in currencies if c and c.upper() != base}
    rates: dict[str, float] = {base: 1.0}
    errors: dict[str, str] = {}
    if wanted:
        with ThreadPoolExecutor(max_workers=min(len(wanted), 10)) as executor:
            futures = {executor.submit(fetch_fx_rate, ccy, base): ccy for ccy in wanted}
            for future in as_completed(futures):
                ccy = futures[future]
                try:
                    rates[ccy] = future.result()
                except RuntimeError as e:
                    errors[ccy] = str(e)
    return FxRates(base=base, rates=rates), errors
