"""Market data from Yahoo Finance, without yfinance or pandas.

Yahoo rejects non-browser TLS fingerprints (plain httpx/curl get HTTP 429),
so requests go through curl_cffi with Chrome impersonation. Quotes use the
batch `spark` endpoint (20 symbols per call, includes intraday closes for
sparklines); history, dividends and search use `chart` and `search`.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import quote as urlquote

from .models import Bar, FxRates, Quote

if TYPE_CHECKING:
    from .db import Store

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
SPARK_URL = "https://query1.finance.yahoo.com/v7/finance/spark"
SEARCH_URL = "https://query2.finance.yahoo.com/v1/finance/search"
SPARK_LIMIT = 20
QUOTE_TTL = 15.0

PERIOD_INTERVALS = {
    "1d": "5m",
    "5d": "30m",
    "1mo": "1h",
    "3mo": "1d",
    "6mo": "1d",
    "ytd": "1d",
    "1y": "1d",
    "2y": "1d",
    "5y": "1wk",
    "10y": "1mo",
    "max": "1mo",
}
PERIODS = list(PERIOD_INTERVALS)
# Bars per year for each chart interval (6.5-hour regular session, 252 trading days)
BARS_PER_YEAR = {"5m": 252 * 78, "30m": 252 * 13, "1h": 252 * 7, "1d": 252, "1wk": 52, "1mo": 12}

# Minor-unit currencies Yahoo uses for some exchanges: (major, divisor)
_MINOR_UNITS = {"GBp": ("GBP", 100.0), "GBX": ("GBP", 100.0), "ZAc": ("ZAR", 100.0), "ILA": ("ILS", 100.0)}


def _gmt_offset(meta: dict) -> int:
    """Exchange UTC offset in seconds from a chart/spark `meta` block (0 if absent)."""
    try:
        return int(meta.get("gmtoffset") or 0)
    except (TypeError, ValueError):
        return 0


def _exchange_date(ts: float, offset: int) -> str:
    return datetime.fromtimestamp(ts + offset, tz=UTC).date().isoformat()


class MarketError(RuntimeError):
    pass


class Transport(Protocol):
    def get_json(self, url: str, params: dict[str, Any]) -> dict: ...


class CurlTransport:
    """curl_cffi session per thread, Chrome TLS fingerprint, retry with backoff."""

    def __init__(self, timeout: float = 10.0, attempts: int = 3, backoff: float = 0.4):
        self.timeout = timeout
        self.attempts = attempts
        self.backoff = backoff
        self._local = threading.local()

    def _session(self):
        session = getattr(self._local, "session", None)
        if session is None:
            from curl_cffi import requests as curl_requests

            session = self._local.session = curl_requests.Session(impersonate="chrome", timeout=self.timeout)
        return session

    def get_json(self, url: str, params: dict[str, Any]) -> dict:
        last: Exception = MarketError("no attempts made")
        for attempt in range(self.attempts):
            try:
                resp = self._session().get(url, params=params)
            except Exception as e:  # curl errors: DNS, timeouts, resets
                last = MarketError(f"network error: {e}")
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()
                    except ValueError:
                        last = MarketError("invalid response from Yahoo")
                elif resp.status_code in (429, 500, 502, 503, 504):
                    last = MarketError(f"Yahoo returned HTTP {resp.status_code}")
                else:
                    # 400/404 carry a JSON error body describing the problem
                    try:
                        return resp.json()
                    except ValueError:
                        raise MarketError(f"Yahoo returned HTTP {resp.status_code}") from None
            if attempt < self.attempts - 1:
                time.sleep(self.backoff * (2**attempt))
        raise last


@dataclass
class SearchResult:
    symbol: str
    name: str
    exchange: str
    type: str


def _market_state(meta: dict, now: float | None = None) -> str:
    if meta.get("instrumentType") == "CRYPTOCURRENCY":
        return "REGULAR"
    periods = meta.get("currentTradingPeriod") or {}
    now = now if now is not None else time.time()
    for key, label in (("regular", "REGULAR"), ("pre", "PRE"), ("post", "POST")):
        p = periods.get(key) or {}
        if p.get("start", 0) <= now < p.get("end", 0):
            return label
    return "CLOSED" if periods else ""


def quote_from_meta(meta: dict, closes: Iterable[float | None] = ()) -> Quote | None:
    price = meta.get("regularMarketPrice")
    if price is None:
        return None
    prev = meta.get("previousClose") or meta.get("chartPreviousClose") or price
    currency = meta.get("currency") or "USD"
    scale = 1.0
    if currency in _MINOR_UNITS:
        currency, scale = _MINOR_UNITS[currency]

    def s(v):
        return None if v is None else float(v) / scale

    return Quote(
        symbol=str(meta.get("symbol", "")).upper(),
        price=float(price) / scale,
        prev_close=float(prev) / scale,
        name=meta.get("longName") or meta.get("shortName") or meta.get("symbol", ""),
        currency=currency,
        exchange=meta.get("fullExchangeName") or meta.get("exchangeName") or "",
        instrument_type=meta.get("instrumentType") or "",
        day_high=s(meta.get("regularMarketDayHigh")),
        day_low=s(meta.get("regularMarketDayLow")),
        volume=int(meta["regularMarketVolume"]) if meta.get("regularMarketVolume") is not None else None,
        week52_high=s(meta.get("fiftyTwoWeekHigh")),
        week52_low=s(meta.get("fiftyTwoWeekLow")),
        market_time=meta.get("regularMarketTime"),
        market_state=_market_state(meta),
        intraday=[float(c) / scale for c in closes if c is not None],
        fetched_at=time.time(),
    )


def _yahoo_error(payload: dict, root: str) -> str | None:
    err = (payload.get(root) or {}).get("error")
    if err:
        return err.get("description") or err.get("code") or "unknown error"
    return None


class MarketData:
    def __init__(self, transport: Transport | None = None, store: Store | None = None):
        self.transport = transport or CurlTransport()
        self.store = store
        self._lock = threading.Lock()
        self._quote_cache: dict[str, tuple[Quote, float]] = {}
        self._history_cache: dict[tuple[str, str], tuple[list[Bar], float]] = {}

    def clear_cache(self) -> None:
        with self._lock:
            self._quote_cache.clear()
            self._history_cache.clear()

    # ── quotes ────────────────────────────────────────────────────────────────

    def _spark(self, symbols: list[str]) -> dict[str, Quote]:
        payload = self.transport.get_json(
            SPARK_URL, {"symbols": ",".join(symbols), "range": "1d", "interval": "5m", "includePrePost": "false"}
        )
        out: dict[str, Quote] = {}
        for item in (payload.get("spark") or {}).get("result") or []:
            response = (item.get("response") or [None])[0]
            if not response:
                continue
            closes = (((response.get("indicators") or {}).get("quote") or [{}])[0]).get("close") or []
            q = quote_from_meta(response.get("meta") or {}, closes)
            if q is not None:
                q.symbol = str(item.get("symbol") or q.symbol).upper()
                out[q.symbol] = q
        return out

    def quotes(self, symbols: Iterable[str], *, use_cache: bool = True) -> tuple[dict[str, Quote], dict[str, str]]:
        """Batch quotes. Returns (quotes, errors). When the network is down,
        last-known quotes come from the store with `stale=True`."""
        wanted = list(dict.fromkeys(s.upper() for s in symbols if s))
        out: dict[str, Quote] = {}
        errors: dict[str, str] = {}
        need = []
        now = time.monotonic()
        with self._lock:
            for sym in wanted:
                entry = self._quote_cache.get(sym)
                if use_cache and entry and entry[1] > now:
                    out[sym] = entry[0]
                else:
                    need.append(sym)
        if not need:
            return out, errors

        chunks = [need[i : i + SPARK_LIMIT] for i in range(0, len(need), SPARK_LIMIT)]

        def run(chunk: list[str]) -> tuple[dict[str, Quote], str | None]:
            try:
                return self._spark(chunk), None
            except MarketError as e:
                return {}, str(e)

        with ThreadPoolExecutor(max_workers=min(len(chunks), 4)) as pool:
            results = list(pool.map(run, chunks))

        fresh: dict[str, Quote] = {}
        offline: list[str] = []
        for chunk, (got, err) in zip(chunks, results, strict=True):
            for sym in chunk:
                if sym in got:
                    fresh[sym] = got[sym]
                elif err:
                    errors[sym] = err
                    offline.append(sym)
                else:
                    errors[sym] = "symbol not found"
        out.update(fresh)
        if fresh:
            expiry = time.monotonic() + QUOTE_TTL
            with self._lock:
                for sym, q in fresh.items():
                    self._quote_cache[sym] = (q, expiry)
        if self.store is not None:
            if fresh:
                self.store.cache_quotes(list(fresh.values()))
            if offline:
                for sym, q in self.store.cached_quotes(offline).items():
                    out[sym] = q
                    errors.pop(sym, None)
        return out, errors

    def quote(self, symbol: str) -> Quote:
        quotes, errors = self.quotes([symbol])
        q = quotes.get(symbol.upper())
        if q is None:
            raise MarketError(f"{symbol.upper()}: {errors.get(symbol.upper(), 'no data')}")
        return q

    # ── FX ────────────────────────────────────────────────────────────────────

    def fx_rates(self, currencies: Iterable[str], base: str) -> tuple[FxRates, dict[str, str]]:
        base = base.upper()
        wanted = sorted({c.upper() for c in currencies if c and c.upper() != base})
        rates = {base: 1.0}
        errors: dict[str, str] = {}
        stale = False
        if wanted:
            pairs = {f"{c}{base}=X": c for c in wanted}
            quotes, errs = self.quotes(pairs)
            for pair, ccy in pairs.items():
                if pair in quotes:
                    rates[ccy] = quotes[pair].price
                else:
                    errors[ccy] = errs.get(pair, "no rate")
            stale = any(quotes[p].stale for p in pairs if p in quotes)
        return FxRates(base=base, rates=rates, stale=stale), errors

    # ── history ───────────────────────────────────────────────────────────────

    def _chart(self, symbol: str, params: dict[str, Any]) -> dict:
        payload = self.transport.get_json(CHART_URL.format(symbol=urlquote(symbol.upper(), safe="")), params)
        if err := _yahoo_error(payload, "chart"):
            raise MarketError(f"{symbol.upper()}: {err}")
        result = ((payload.get("chart") or {}).get("result") or [None])[0]
        if not result:
            raise MarketError(f"{symbol.upper()}: no data")
        return result

    @staticmethod
    def _bars(result: dict) -> list[Bar]:
        stamps = result.get("timestamp") or []
        q = ((result.get("indicators") or {}).get("quote") or [{}])[0]
        meta = result.get("meta") or {}
        scale = _MINOR_UNITS.get(meta.get("currency") or "", ("", 1.0))[1]
        offset = _gmt_offset(meta)
        opens, highs, lows, closes, vols = (q.get(k) or [] for k in ("open", "high", "low", "close", "volume"))

        def pick(seq: list, i: int, default: float) -> float:
            v = seq[i] if i < len(seq) else None
            return default if v is None else v

        bars = []
        for i, ts in enumerate(stamps):
            c = closes[i] if i < len(closes) else None
            if c is None:
                continue
            bars.append(
                Bar(
                    float(ts),
                    pick(opens, i, c) / scale,
                    pick(highs, i, c) / scale,
                    pick(lows, i, c) / scale,
                    c / scale,
                    int(pick(vols, i, 0) or 0),
                    offset,
                )
            )
        return bars

    def history(self, symbol: str, period: str = "3mo") -> list[Bar]:
        if period not in PERIOD_INTERVALS:
            raise MarketError(f"Unknown period '{period}'. Choose from: {', '.join(PERIODS)}")
        key = (symbol.upper(), period)
        now = time.monotonic()
        with self._lock:
            entry = self._history_cache.get(key)
            if entry and entry[1] > now:
                return entry[0]
        result = self._chart(symbol, {"range": period, "interval": PERIOD_INTERVALS[period], "includePrePost": "false"})
        bars = self._bars(result)
        ttl = 60.0 if period in ("1d", "5d") else 600.0
        with self._lock:
            self._history_cache[key] = (bars, time.monotonic() + ttl)
        return bars

    def daily_closes(self, symbol: str, start: str) -> tuple[dict[str, float], str]:
        """Daily closes keyed by ISO date from `start` to today, plus the currency."""
        # A day early, in UTC, so exchanges east of Greenwich keep their first session
        t0 = int(datetime.combine(date.fromisoformat(start), datetime.min.time(), tzinfo=UTC).timestamp())
        t0 -= 86400
        result = self._chart(symbol, {"period1": t0, "period2": int(time.time()) + 86400, "interval": "1d"})
        currency = (result.get("meta") or {}).get("currency") or "USD"
        currency = _MINOR_UNITS.get(currency, (currency, 1.0))[0]
        return {b.date: b.close for b in self._bars(result)}, currency

    def dividends(self, symbol: str, period: str = "1y") -> list[tuple[str, float]]:
        """Per-share cash distributions within `period`, oldest first."""
        result = self._chart(symbol, {"range": period, "interval": "1d", "events": "div"})
        meta = result.get("meta") or {}
        scale = _MINOR_UNITS.get(meta.get("currency") or "", ("", 1.0))[1]
        offset = _gmt_offset(meta)
        events = ((result.get("events") or {}).get("dividends") or {}).values()
        return sorted(
            (_exchange_date(e["date"], offset), float(e["amount"]) / scale)
            for e in events
            if "date" in e and "amount" in e
        )

    # ── search ────────────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 8) -> list[SearchResult]:
        if not query.strip():
            return []
        payload = self.transport.get_json(
            SEARCH_URL,
            {"q": query.strip(), "quotesCount": limit, "newsCount": 0, "listsCount": 0, "enableFuzzyQuery": "true"},
        )
        return [
            SearchResult(
                symbol=str(q["symbol"]).upper(),
                name=q.get("longname") or q.get("shortname") or q["symbol"],
                exchange=q.get("exchDisp") or q.get("exchange") or "",
                type=q.get("typeDisp") or q.get("quoteType") or "",
            )
            for q in payload.get("quotes") or []
            if q.get("symbol")
        ]
