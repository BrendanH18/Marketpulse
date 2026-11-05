"""Fallback quote providers, used only when Yahoo can't be reached.

Each one needs an API key the user supplies (`marketpulse provider key NAME`).
No key ships with MarketPulse. Keys never appear in error messages, logs,
exports or the desktop bridge: any error text is scrubbed of the key before it
leaves the provider.

Alpha Vantage is the one free tier that covers the TSX. Its free quote is the
latest daily close, one symbol per call, 25 calls a day: enough to keep a
portfolio's prices from going days stale when Yahoo is unreachable, not to
replace Yahoo.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from zoneinfo import ZoneInfo

from .market import CurlTransport, MarketError, QuoteProvider, Transport
from .models import Quote

if TYPE_CHECKING:
    from .config import Config


@dataclass(frozen=True)
class ProviderInfo:
    name: str
    label: str
    signup_url: str
    factory: Callable[[str, Transport | None], QuoteProvider]


ALPHA_VANTAGE_URL = "https://www.alphavantage.co/query"
# Yahoo listing suffix -> Alpha Vantage suffix, and the listing currency.
_AV_SUFFIXES = {".TO": (".TRT", "CAD"), ".V": (".TRV", "CAD")}
_FX = re.compile(r"^([A-Z]{3})([A-Z]{3})=X$")
_CRYPTO = re.compile(r"^([A-Z0-9]{2,10})-([A-Z]{3})$")
_PLAIN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_NEW_YORK = ZoneInfo("America/New_York")


def _number(row: dict, key: str) -> float | None:
    try:
        return float(row[key])
    except (KeyError, TypeError, ValueError):
        return None


class AlphaVantage:
    """Latest quotes from Alpha Vantage: GLOBAL_QUOTE for listings, CURRENCY_EXCHANGE_RATE
    for currency pairs and crypto. Symbols use Yahoo's spelling in and out."""

    name = "alphavantage"
    label = "Alpha Vantage"
    batch_limit = 5  # its free tier allows 5 calls a minute
    min_interval = 900.0
    daily_limit = 25

    def __init__(self, key: str, transport: Transport | None = None):
        self._key = key
        self.transport = transport or CurlTransport(attempts=1, service=self.label)

    def _get(self, params: dict[str, Any]) -> dict:
        try:
            payload = self.transport.get_json(ALPHA_VANTAGE_URL, {**params, "apikey": self._key})
        except MarketError as e:
            raise MarketError(redact(str(e), self._key)) from None
        if not isinstance(payload, dict):
            raise MarketError(f"invalid response from {self.label}")
        # Every reply is HTTP 200; refusals (bad key, rate limit) are a top-level message.
        for key in ("Error Message", "Information", "Note"):
            if payload.get(key):
                raise MarketError(f"{self.label}: {redact(str(payload[key]), self._key)}")
        return payload

    @staticmethod
    def listing(symbol: str) -> tuple[str, str] | None:
        """(Alpha Vantage symbol, currency) for a Yahoo listing symbol it covers."""
        for suffix, (av, currency) in _AV_SUFFIXES.items():
            if symbol.endswith(suffix) and _PLAIN.match(symbol[: -len(suffix)]):
                return symbol[: -len(suffix)] + av, currency
        if "." not in symbol and _PLAIN.match(symbol):
            return symbol, "USD"  # US listings have no suffix on either side
        return None

    def _listing_quote(self, symbol: str, av: str, currency: str) -> Quote | None:
        row = self._get({"function": "GLOBAL_QUOTE", "symbol": av}).get("Global Quote") or {}
        price = _number(row, "05. price")
        if price is None:
            return None
        prev = _number(row, "08. previous close")
        market_time = None
        try:  # its "latest trading day": the price is that day's close
            day = datetime.strptime(str(row["07. latest trading day"]), "%Y-%m-%d")
            market_time = day.replace(hour=16, tzinfo=_NEW_YORK).timestamp()
        except (KeyError, ValueError):
            pass
        volume = _number(row, "06. volume")
        return Quote(
            symbol=symbol,
            price=price,
            prev_close=prev if prev is not None else price,
            name=symbol,
            currency=currency,
            day_high=_number(row, "03. high"),
            day_low=_number(row, "04. low"),
            volume=int(volume) if volume is not None else None,
            market_time=market_time,
            market_state="CLOSED",
            fetched_at=time.time(),
        )

    def _rate_quote(self, symbol: str, base: str, quote: str) -> Quote | None:
        row = (
            self._get({"function": "CURRENCY_EXCHANGE_RATE", "from_currency": base, "to_currency": quote}).get(
                "Realtime Currency Exchange Rate"
            )
            or {}
        )
        rate = _number(row, "5. Exchange Rate")
        if rate is None:
            return None
        market_time = None
        try:
            stamp = datetime.strptime(str(row["6. Last Refreshed"]), "%Y-%m-%d %H:%M:%S")
            market_time = stamp.replace(tzinfo=ZoneInfo(str(row.get("7. Time Zone") or "UTC"))).timestamp()
        except (KeyError, ValueError):
            pass
        crypto = not symbol.endswith("=X")
        return Quote(
            symbol=symbol,
            price=rate,
            prev_close=rate,  # no previous close from this endpoint: no day change, rather than a wrong one
            name=f"{base}/{quote}",
            currency=quote,
            instrument_type="CRYPTOCURRENCY" if crypto else "CURRENCY",
            market_time=market_time,
            market_state="REGULAR" if crypto else "",
            fetched_at=time.time(),
        )

    def quotes(self, symbols: list[str]) -> tuple[dict[str, Quote], dict[str, str]]:
        out: dict[str, Quote] = {}
        errors: dict[str, str] = {}
        for symbol in symbols:
            sym = symbol.upper()
            if m := _FX.match(sym) or _CRYPTO.match(sym):
                q = self._rate_quote(sym, m.group(1), m.group(2))
            elif listing := self.listing(sym):
                q = self._listing_quote(sym, *listing)
            else:
                errors[sym] = f"not covered by {self.label}"
                continue
            if q is None:
                errors[sym] = "symbol not found"
            else:
                out[sym] = q
        return out, errors


PROVIDERS: dict[str, ProviderInfo] = {
    AlphaVantage.name: ProviderInfo(
        AlphaVantage.name, AlphaVantage.label, "https://www.alphavantage.co/support/#api-key", AlphaVantage
    ),
}


def provider_label(name: str) -> str:
    if name == "yahoo":
        return "Yahoo Finance"
    info = PROVIDERS.get(name)
    return info.label if info else name


def make_fallback(config: Config, transport: Transport | None = None) -> QuoteProvider | None:
    """The configured fallback, or None when none is chosen or it has no key."""
    info = PROVIDERS.get(config.quote_provider)
    if info is None or not config.quote_api_key:
        return None
    return info.factory(config.quote_api_key, transport)


def redact(message: str, secret: str) -> str:
    """`message` with every occurrence of `secret` replaced."""
    return message.replace(secret, "***") if secret else message
