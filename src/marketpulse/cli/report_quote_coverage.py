"""Offline quote-cache coverage for saved watchlists and alerts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from ..models import Quote
from .base import App

GROUP = "portfolio"
_CACHE_FIELDS = ("has_cached_quote", "quote_source", "quote_currency", "fetched_at", "fetch_time_known")
SOURCES = {
    "watchlist-quote-coverage": ("position", "symbol", *_CACHE_FIELDS),
    "alert-quote-coverage": ("alert_id", "symbol", "condition", "active", "triggered_at", *_CACHE_FIELDS),
}
DESCRIPTIONS = {
    "watchlist-quote-coverage": "Watched symbols in watchlist order with their saved quote-cache metadata.",
    "alert-quote-coverage": "Saved alerts and their recorded state alongside quote-cache metadata for each symbol.",
}
PRESETS = {
    "watchlist-quote-coverage": {
        "cached": ("in_values", "has_cached_quote=[true]"),
        "uncached": ("in_values", "has_cached_quote=[false]"),
        "missing-fetch-time": ("in_values", "fetch_time_known=[false]"),
    },
    "alert-quote-coverage": {
        "active": ("in_values", "active=[true]"),
        "uncached": ("in_values", "has_cached_quote=[false]"),
        "triggered": ("nonempty", "triggered_at"),
    },
}


def _fetch_time(quote: Quote) -> str | None:
    if not quote.fetched_at:
        return None
    try:
        return datetime.fromtimestamp(quote.fetched_at, UTC).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _cache_metadata(quote: Quote | None) -> dict[str, Any]:
    fetched_at = _fetch_time(quote) if quote is not None else None
    return {
        "has_cached_quote": quote is not None,
        "quote_source": quote.source if quote is not None else None,
        "quote_currency": quote.currency if quote is not None else None,
        "fetched_at": fetched_at,
        "fetch_time_known": fetched_at is not None if quote is not None else None,
    }


def load_source(name: str, app: App) -> list[dict[str, Any]]:
    if name not in SOURCES:
        raise KeyError(name)
    store = app.store
    with store._read_snapshot():
        if name == "watchlist-quote-coverage":
            watchlist = store.watchlist()
            quotes = store.cached_quotes(watchlist)
            return [
                {"position": position, "symbol": symbol, **_cache_metadata(quotes.get(symbol))}
                for position, symbol in enumerate(watchlist, 1)
            ]
        alerts = store.alerts()
        quotes = store.cached_quotes(sorted({alert.symbol for alert in alerts}))
        return [
            {
                "alert_id": alert.saved_id,
                "symbol": alert.symbol,
                "condition": alert.condition,
                "active": alert.active,
                "triggered_at": alert.triggered_at or None,
                **_cache_metadata(quotes.get(alert.symbol)),
            }
            for alert in alerts
        ]
