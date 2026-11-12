"""Market data: quotes, charts, comparisons and symbol search."""

from __future__ import annotations

import csv
import io
import json
import re
import time
from datetime import datetime

import click
from rich.table import Table
from rich.text import Text

from .. import fmt, render
from ..market import BARS_PER_YEAR, PERIOD_INTERVALS, PERIODS, MarketError
from ..models import Quote, parse_symbols
from .base import App, fail, pass_app
from .root import main

DURATION_UNITS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
CACHE_SORTS = ("symbol", "age", "change")
QUOTE_FIELDS = [
    "symbol",
    "name",
    "price",
    "prev_close",
    "change",
    "change_pct",
    "currency",
    "stale",
    "fetched_at",
    "source",
    "error",
]


def _duration_callback(ctx, param, value: str | None) -> float | None:
    """Parse a cache age such as `90s`, `30m`, `2h`, `3d` or `1w` into seconds."""
    if value is None:
        return None
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhdw])\s*", value.lower())
    if not m or float(m.group(1)) <= 0:
        raise click.BadParameter("use a positive number with a unit: s, m, h, d or w (e.g. 30m, 2h, 3d).")
    return float(m.group(1)) * DURATION_UNITS[m.group(2)]


def _cache_sort_key(sort: str, now: float):
    def key(q: Quote) -> tuple:
        if sort == "age":
            age = q.age(now)
            return (age is None, age or 0.0, q.symbol)
        if sort == "change":
            return (q.change_pct, q.symbol)
        return (q.symbol,)

    return key


@main.command()
@click.argument("symbols", nargs=-1)
@click.option("--cached", is_flag=True, help="Show the saved offline quote cache; no network request.")
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable quotes, with per-symbol errors.")
@click.option("--all", "all_cached", is_flag=True, help="With --cached: every cached symbol, no symbols needed.")
@click.option("--currency", "currencies", multiple=True, help="With --cached: only this quote currency (repeatable).")
@click.option("--search", help="With --cached: symbol or name contains this text (ignores case).")
@click.option(
    "--older-than", callback=_duration_callback, help="With --cached: cached at least this long ago (30m, 2h, 3d, 1w)."
)
@click.option(
    "--newer-than", callback=_duration_callback, help="With --cached: cached less than this long ago (30m, 2h, 3d, 1w)."
)
@click.option("--sort", type=click.Choice(CACHE_SORTS), help="With --cached: order by symbol, cache age or % change.")
@click.option("--descending", is_flag=True, help="With --cached --sort: reverse the order.")
@click.option("--csv", "as_csv", is_flag=True, help="With --cached: print cached quotes as CSV to stdout.")
@pass_app
def quote(
    app: App,
    symbols: tuple[str, ...],
    cached: bool,
    as_json: bool,
    all_cached: bool,
    currencies: tuple[str, ...],
    search: str | None,
    older_than: float | None,
    newer_than: float | None,
    sort: str | None,
    descending: bool,
    as_csv: bool,
) -> None:
    """Live quotes. One symbol shows a detail card.

    With --cached, read only the saved offline cache; --all, --currency, --search,
    --older-than, --newer-than, --sort, --descending and --csv refine that view.
    """
    cache_opts = {
        "--all": all_cached,
        "--currency": bool(currencies),
        "--search": search is not None,
        "--older-than": older_than is not None,
        "--newer-than": newer_than is not None,
        "--sort": sort is not None,
        "--descending": descending,
        "--csv": as_csv,
    }
    used = [name for name, on in cache_opts.items() if on]
    if used and not cached:
        raise click.UsageError(f"{', '.join(used)} require{'s' if len(used) == 1 else ''} --cached.")
    if all_cached and symbols:
        raise click.UsageError("Give symbols or --all, not both.")
    syms = [] if all_cached else parse_symbols(" ".join(symbols))
    if not syms and not all_cached:
        raise click.UsageError("Give at least one symbol" + (", or use --all." if cached else "."))
    if as_json and as_csv:
        raise click.UsageError("Choose one output format: --json or --csv.")
    if descending and sort is None:
        raise click.UsageError("--descending requires --sort.")
    if search is not None and not search.strip():
        raise click.UsageError("--search cannot be blank.")
    if any(not c.strip() for c in currencies):
        raise click.UsageError("--currency cannot be blank.")
    if older_than is not None and newer_than is not None and older_than >= newer_than:
        raise click.UsageError("--older-than must be shorter than --newer-than.")
    if cached:
        _cached_quotes(
            app,
            syms,
            all_cached=all_cached,
            currencies={c.strip().upper() for c in currencies},
            search=search.strip().lower() if search else None,
            older_than=older_than,
            newer_than=newer_than,
            sort=sort,
            descending=descending,
            as_json=as_json,
            as_csv=as_csv,
        )
        return
    if as_json:
        quotes, errors = app.tracker.market.quotes(syms)
    else:
        with app.busy("Fetching quotes…"):
            quotes, errors = app.tracker.market.quotes(syms)
    found = any(s in quotes for s in syms)
    if as_json:
        click.echo(json.dumps([_quote_json(s, quotes.get(s), errors) for s in syms], ensure_ascii=False))
        if not found:
            click.get_current_context().exit(1)
        return
    if len(syms) == 1:
        q = quotes.get(syms[0])
        if q is None:
            fail(f"{syms[0]}: {errors.get(syms[0], 'no data')}")
        app.console.print(render.quote_card(q))
        return
    app.console.print(render.quotes_table(syms, quotes, errors, width=app.console.width))


def _cached_quotes(
    app: App,
    syms: list[str],
    *,
    all_cached: bool,
    currencies: set[str],
    search: str | None,
    older_than: float | None,
    newer_than: float | None,
    sort: str | None,
    descending: bool,
    as_json: bool,
    as_csv: bool,
) -> None:
    """Render the offline cache: strictly reads `quote_cache`, never the network."""
    quotes = app.store.all_cached_quotes() if all_cached else app.store.cached_quotes(syms)
    errors = {s: "not in the offline cache" for s in syms if s not in quotes}
    now = time.time()

    def keep(q: Quote) -> bool:
        age = q.age(now)
        return (
            (not currencies or q.currency.upper() in currencies)
            and (search is None or search in q.symbol.lower() or search in (q.name or "").lower())
            and (older_than is None or (age is not None and age >= older_than))
            and (newer_than is None or (age is not None and age < newer_than))
        )

    selected = [q for q in quotes.values() if keep(q)]
    # Named symbols keep their given order (missing ones in place); otherwise the cache is A–Z.
    order = list(quotes) if all_cached else syms
    if sort:
        selected.sort(key=_cache_sort_key(sort, now), reverse=descending)
        order = [q.symbol for q in selected] + list(errors)
    else:
        kept = {q.symbol for q in selected}
        order = [s for s in order if s in kept or s in errors]
    shown = {q.symbol: q for q in selected}
    found = bool(shown)
    if as_json or as_csv:
        rows = [_quote_json(s, shown.get(s), errors) for s in order]
        if as_json:
            click.echo(json.dumps(rows, ensure_ascii=False))
        else:
            stream = io.StringIO()
            writer = csv.DictWriter(stream, fieldnames=QUOTE_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            click.echo(stream.getvalue(), nl=False)
        if not found:
            click.get_current_context().exit(1)
        return
    if not found:
        if not quotes and all_cached:
            fail("The offline quote cache is empty. Run `marketpulse quote` online to fill it.")
        if quotes:
            fail("No cached quotes match the filters.")
        fail("No cached quotes for " + ", ".join(syms) + ". Run `marketpulse quote` online to fill the cache.")
    app.console.print(_cached_table(order, shown))
    for s in order:
        if s in errors:
            app.warn(f"{s}: {errors[s]}")


def _iso(epoch: float | None) -> str | None:
    """Local ISO time with its UTC offset, or None when unknown."""
    return datetime.fromtimestamp(epoch).astimezone().isoformat(timespec="seconds") if epoch else None


def _quote_json(symbol: str, q: Quote | None, errors: dict[str, str]) -> dict:
    if q is None:
        return {
            "symbol": symbol,
            "name": None,
            "price": None,
            "prev_close": None,
            "change": None,
            "change_pct": None,
            "currency": None,
            "stale": None,
            "fetched_at": None,
            "source": None,
            "error": errors.get(symbol, "no data"),
        }
    return {
        "symbol": q.symbol,
        "name": q.name,
        "price": q.price,
        "prev_close": q.prev_close,
        "change": q.change,
        "change_pct": q.change_pct,
        "currency": q.currency,
        "stale": q.stale,
        "fetched_at": _iso(q.fetched_at),
        "source": q.source,
        "error": None,
    }


def _cached_table(symbols: list[str], quotes: dict[str, Quote]) -> Table:
    t = render.table(
        "Symbol",
        "Name",
        ("Price", "right"),
        ("Chg", "right"),
        ("%", "right"),
        "Ccy",
        "Cached at",
        title="Cached quotes (offline)",
    )
    for s in symbols:
        q = quotes.get(s)
        if q is None:
            continue
        fetched = _iso(q.fetched_at)
        t.add_row(
            Text(q.symbol, style="bright"),
            Text(render.truncate(q.name, 28), style="muted"),
            Text(fmt.price(q.price) + " ◌"),
            render.trend(f"{q.change:+,.2f}", q.change),
            render.trend(f"{fmt.arrow(q.change)} {fmt.pct(q.change_pct)}", q.change),
            Text(q.currency, style="muted"),
            Text(f"{fetched[:19].replace('T', ' ')} · {fmt.age(q.age())} ago" if fetched else "unknown", style="warn"),
        )
    return t


@main.command()
@click.argument("symbol")
@click.option("-p", "--period", type=click.Choice(PERIODS), default=None, help="Default from config (chart_period).")
@click.option("--vs", "versus", multiple=True, help="Overlay other symbols as % change.")
@click.option("-H", "--height", type=int, default=16, show_default=True)
@pass_app
def chart(app: App, symbol: str, period: str | None, versus: tuple[str, ...], height: int) -> None:
    """Braille price chart, optionally compared against other symbols."""
    period = period or app.config.chart_period
    market = app.tracker.market
    try:
        with app.busy(f"Fetching {symbol.upper()} {period}…"):
            bars = market.history(symbol, period)
            others = {v.upper(): market.history(v, period) for v in versus}
            quotes, _ = market.quotes([symbol])
    except MarketError as e:
        fail(str(e))
    q = quotes.get(symbol.upper())
    if q:
        app.console.print(render.quote_card(q))
        app.console.print()
    app.console.print(
        render.price_chart(
            symbol.upper(),
            bars,
            period,
            app.palette,
            width=app.console.width - 1,
            height=height,
            quote=q,
            compare=others or None,
        )
    )


@main.command()
@click.argument("symbols", nargs=-1, required=True)
@click.option("-p", "--period", type=click.Choice(PERIODS), default="1y", show_default=True)
@pass_app
def compare(app: App, symbols: tuple[str, ...], period: str) -> None:
    """Compare returns, drawdown and volatility across symbols."""
    from ..analytics import max_drawdown, period_return, volatility

    syms = parse_symbols(" ".join(symbols))
    market = app.tracker.market
    data = {}
    with app.busy(f"Fetching {len(syms)} histories…"):
        for s in syms:
            try:
                data[s] = market.history(s, period)
            except MarketError as e:
                app.warn(str(e))
    data = {k: v for k, v in data.items() if v}
    if not data:
        fail("No data retrieved.")
    first, *rest = data
    app.console.print(
        render.price_chart(
            first,
            data[first],
            period,
            app.palette,
            width=app.console.width - 1,
            compare={r: data[r] for r in rest} or None,
        )
    )
    t = render.table(
        "Symbol",
        ("Start", "right"),
        ("End", "right"),
        ("Return", "right"),
        ("Max drawdown", "right"),
        ("Volatility", "right"),
        title=f"\n{period} comparison",
    )
    for s, bars in sorted(data.items(), key=lambda kv: period_return([b.close for b in kv[1]]) or 0, reverse=True):
        closes = [b.close for b in bars]
        ret = period_return(closes)
        per_year = BARS_PER_YEAR[PERIOD_INTERVALS[period]]
        t.add_row(
            Text(s, style="bright"),
            Text(fmt.price(closes[0]), style="muted"),
            Text(fmt.price(closes[-1])),
            render.trend(fmt.pct(ret), ret),
            Text(fmt.pct(max_drawdown(closes)), style="down"),
            Text(fmt.pct(volatility(closes, per_year), sign=False), style="muted"),
        )
    app.console.print(t)


@main.command()
@click.argument("query", nargs=-1, required=True)
@pass_app
def search(app: App, query: tuple[str, ...]) -> None:
    """Find symbols by company or fund name."""
    try:
        with app.busy("Searching…"):
            results = app.tracker.market.search(" ".join(query), limit=12)
    except MarketError as e:
        fail(str(e))
    if not results:
        fail("No matches.")
    app.console.print(render.search_table(results))
