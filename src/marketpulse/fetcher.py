"""Market data fetching via yfinance."""
import yfinance as yf
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from .models import Quote


def fetch_quote(ticker: str) -> Quote:
    """Fetch a single live quote for a ticker."""
    try:
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
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {ticker}: {e}") from e


def fetch_quotes(tickers: list[str]) -> tuple[dict[str, Quote], dict[str, str]]:
    """Fetch quotes for multiple tickers in parallel.

    Returns (quotes, errors): quotes keyed by upper-cased ticker, and an
    error-message dict for every ticker that failed.
    """
    if not tickers:
        return {}, {}
    results = {}
    errors = {}
    with ThreadPoolExecutor(max_workers=min(len(tickers), 10)) as executor:
        futures = {executor.submit(fetch_quote, ticker): ticker for ticker in tickers}
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
    import pandas as pd
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period=period)
        return hist
    except Exception as e:
        raise RuntimeError(f"Failed to fetch history for {ticker}: {e}") from e
