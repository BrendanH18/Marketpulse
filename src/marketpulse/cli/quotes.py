"""Market data: quotes, charts, comparisons and symbol search."""

from __future__ import annotations

import json
from datetime import datetime

import click
from rich.table import Table
from rich.text import Text

from .. import fmt, render
from ..market import BARS_PER_YEAR, PERIOD_INTERVALS, PERIODS, MarketError
from ..models import Quote, parse_symbols
from .base import App, fail, pass_app
from .root import main


@main.command()
@click.argument("symbols", nargs=-1, required=True)
@click.option("--cached", is_flag=True, help="Show the saved offline quote cache; no network request.")
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable quotes, with per-symbol errors.")
@pass_app
def quote(app: App, symbols: tuple[str, ...], cached: bool, as_json: bool) -> None:
    """Live quotes. One symbol shows a detail card."""
    syms = parse_symbols(" ".join(symbols))
    if not syms:
        raise click.UsageError("Give at least one symbol.")
    if cached:
        quotes = app.store.cached_quotes(syms)
        errors = {s: "not in the offline cache" for s in syms if s not in quotes}
    elif as_json:
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
    if cached:
        if not found:
            fail("No cached quotes for " + ", ".join(syms) + ". Run `marketpulse quote` online to fill the cache.")
        app.console.print(_cached_table(syms, quotes))
        for s in syms:
            if s not in quotes:
                app.warn(f"{s}: {errors[s]}")
        return
    if len(syms) == 1:
        q = quotes.get(syms[0])
        if q is None:
            fail(f"{syms[0]}: {errors.get(syms[0], 'no data')}")
        app.console.print(render.quote_card(q))
        return
    app.console.print(render.quotes_table(syms, quotes, errors, width=app.console.width))


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
