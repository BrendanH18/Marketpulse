"""Market data: quotes, charts, comparisons and symbol search."""

from __future__ import annotations

import csv
import io
import json
import re
import time
from contextlib import nullcontext
from datetime import datetime

import click
from rich.console import Group
from rich.table import Table
from rich.text import Text

from .. import charts, fmt, render
from ..market import BARS_PER_YEAR, PERIOD_INTERVALS, PERIODS, MarketError
from ..models import Bar, Quote, parse_symbols
from ..themes import Palette
from .base import App, date_callback, fail, pass_app
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
VALUE_FIELDS = ("price", "prev_close", "change", "change_pct", "currency", "name", "exchange", "volume")


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
@click.option("--field", type=click.Choice(VALUE_FIELDS), help="Print one bare value per symbol, for scripts.")
@click.option("--strict", is_flag=True, help="Exit 1 when any named symbol has no quote.")
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
    field: str | None,
    strict: bool,
) -> None:
    """Live quotes. One symbol shows a detail card.

    With --cached, read only the saved offline cache; --all, --currency, --search,
    --older-than, --newer-than, --sort, --descending and --csv refine that view.
    --field prints bare live values; --strict exits 1 when any symbol is missing.
    """
    if field and (cached or as_json):
        raise click.UsageError("--field prints live values; it can't be combined with --cached or --json.")
    if strict and cached:
        raise click.UsageError("--strict applies to live quotes, not --cached.")
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
    if as_json or field:
        quotes, errors = app.tracker.market.quotes(syms)
    else:
        with app.busy("Fetching quotes…"):
            quotes, errors = app.tracker.market.quotes(syms)
    found = any(s in quotes for s in syms)
    missing = any(s not in quotes for s in syms)
    if field:
        _print_field(syms, quotes, errors, field)
        if not found or (strict and missing):
            click.get_current_context().exit(1)
        return
    if as_json:
        click.echo(json.dumps([_quote_json(s, quotes.get(s), errors) for s in syms], ensure_ascii=False))
        if not found or (strict and missing):
            click.get_current_context().exit(1)
        return
    if len(syms) == 1:
        q = quotes.get(syms[0])
        if q is None:
            fail(f"{syms[0]}: {errors.get(syms[0], 'no data')}")
        app.console.print(render.quote_card(q))
        return
    app.console.print(render.quotes_table(syms, quotes, errors, width=app.console.width))
    if strict and missing:
        click.get_current_context().exit(1)


def _print_field(syms: list[str], quotes: dict[str, Quote], errors: dict[str, str], field: str) -> None:
    """One value per line: bare for one symbol, `SYMBOL<tab>value` for several; misses go to stderr."""
    for s in syms:
        q = quotes.get(s)
        if q is None:
            click.echo(f"{s}: {errors.get(s, 'no data')}", err=True)
            continue
        value = getattr(q, field)
        text = "" if value is None else str(value)
        click.echo(text if len(syms) == 1 else f"{s}\t{text}")


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
        if sort == "age":
            # Unknown cache times stay last in both directions (the sort is stable).
            selected.sort(key=lambda q: q.age(now) is None)
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
            for s in order:
                if s in errors:
                    app.warn(f"{s}: {errors[s]}")
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


CHART_FIELDS = ["symbol", "date", "time", "open", "high", "low", "close", "volume"]
STATS_FIELDS = [
    "symbol",
    "period",
    "interval",
    "from",
    "to",
    "bars",
    "first",
    "last",
    "change",
    "change_pct",
    "high",
    "high_date",
    "low",
    "low_date",
    "max_drawdown_pct",
    "volatility_pct",
]
COMPARE_FIELDS = [
    "symbol",
    "period",
    "interval",
    "from",
    "to",
    "bars",
    "start",
    "end",
    "return_pct",
    "max_drawdown_pct",
    "volatility_pct",
    "vs_base_pp",
]
COMPARE_SORTS = ("return", "drawdown", "volatility", "symbol")
SEARCH_FIELDS = ["symbol", "name", "exchange", "type"]
SEARCH_LIMIT = 12  # results requested from the search endpoint, as always


def _csv_text(fields: list[str], rows: list[dict]) -> str:
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def _trim(bars: list[Bar], start: str | None, end: str | None, last: int | None) -> list[Bar]:
    """Keep the bars of an already-fetched series whose exchange date is in range, then the last N."""
    kept = [b for b in bars if (start is None or b.date >= start) and (end is None or b.date <= end)]
    return kept[-last:] if last else kept


def _bar_json(symbol: str, b: Bar) -> dict:
    return {
        "symbol": symbol,
        "date": b.date,
        "time": b.local().isoformat(timespec="seconds"),
        "open": b.open,
        "high": b.high,
        "low": b.low,
        "close": b.close,
        "volume": b.volume,
    }


def _series_stats(symbol: str, bars: list[Bar], period: str) -> dict:
    """Summary of one fetched series, using the same helpers as the chart footer and `compare`."""
    from ..analytics import max_drawdown, period_return, volatility

    interval = PERIOD_INTERVALS[period]
    closes = [b.close for b in bars]
    row: dict = dict.fromkeys(STATS_FIELDS)
    row.update(symbol=symbol, period=period, interval=interval, bars=len(bars))
    if not closes:
        return row
    hi = max(range(len(closes)), key=closes.__getitem__)
    lo = min(range(len(closes)), key=closes.__getitem__)
    row.update(
        {
            "from": bars[0].date,
            "to": bars[-1].date,
            "first": closes[0],
            "last": closes[-1],
            "change": closes[-1] - closes[0],
            "change_pct": period_return(closes),
            "high": closes[hi],
            "high_date": bars[hi].date,
            "low": closes[lo],
            "low_date": bars[lo].date,
            "max_drawdown_pct": max_drawdown(closes),
            "volatility_pct": volatility(closes, BARS_PER_YEAR[interval]),
        }
    )
    return row


def _stats_table(rows: list[dict], period: str) -> Table:
    main_row = rows[0]
    span = f" · {main_row['from']} to {main_row['to']} · {main_row['bars']} bars" if main_row["bars"] else ""
    t = render.table(
        "Symbol",
        ("First", "right"),
        ("Last", "right"),
        ("Change", "right"),
        ("%", "right"),
        ("High", "right"),
        ("Low", "right"),
        ("Max drawdown", "right"),
        ("Volatility", "right"),
        title=f"{period} statistics{span}",
    )
    for r in rows:
        chg = r["change_pct"]
        t.add_row(
            Text(r["symbol"], style="bright"),
            Text(fmt.price(r["first"]), style="muted"),
            Text(fmt.price(r["last"])),
            render.trend(f"{r['change']:+,.2f}" if r["change"] is not None else render.DASH, r["change"]),
            render.trend(f"{fmt.arrow(chg)} {fmt.pct(chg)}" if chg is not None else render.DASH, chg),
            Text(fmt.price(r["high"])),
            Text(fmt.price(r["low"])),
            Text(fmt.pct(r["max_drawdown_pct"]), style="down"),
            Text(fmt.pct(r["volatility_pct"], sign=False), style="muted"),
        )
    return t


def _x_labels(bars: list[Bar], period: str) -> tuple[str, str]:
    if period in ("1d", "5d"):
        f = "%H:%M" if period == "1d" else "%b %d %H:%M"
        return bars[0].local().strftime(f), bars[-1].local().strftime(f)
    return bars[0].date, bars[-1].date


def _normalized_chart(symbol: str, bars: list[Bar], period: str, palette: Palette, *, width: int, height: int):
    """One series drawn as % change from its first close, like a `--vs` overlay."""
    closes = [b.close for b in bars]
    if not closes or not closes[0]:
        return Text(f"No {period} history for {symbol}.", style="muted")
    series = [(c / closes[0] - 1) * 100 for c in closes]
    ret = series[-1]
    color = palette.up if ret >= 0 else palette.down
    legend = Text()
    legend.append(f"━━ {symbol} ", style=f"bold {color}")
    legend.append(fmt.pct(ret), style=fmt.trend_style(ret))
    drawn = charts.braille_chart(
        [series],
        width,
        height,
        [color],
        baseline=0.0,
        label_format="{:+.1f}%",
        x_labels=_x_labels(bars, period),
    )
    return Group(legend, Text(""), drawn)


@main.command()
@click.argument("symbol")
@click.option("-p", "--period", type=click.Choice(PERIODS), default=None, help="Default from config (chart_period).")
@click.option("--vs", "versus", multiple=True, help="Overlay other symbols as % change.")
@click.option("-H", "--height", type=int, default=16, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Print the plotted bars (and --vs bars) as JSON, no chart.")
@click.option("--csv", "as_csv", is_flag=True, help="Print the plotted bars (and --vs bars) as CSV, no chart.")
@click.option("--stats", is_flag=True, help="Print first, last, change, high, low, drawdown and volatility, no chart.")
@click.option("--from", "start", callback=date_callback, help="Keep fetched bars on or after this date.")
@click.option("--to", "end", callback=date_callback, help="Keep fetched bars on or before this date.")
@click.option("--last", type=click.IntRange(min=2), help="Keep only the last N fetched bars.")
@click.option("--normalize", is_flag=True, help="Draw % change from the first bar instead of price.")
@click.option("-w", "--width", type=click.IntRange(min=20), help="Chart width in columns (default: the terminal's).")
@click.option("--no-card", is_flag=True, help="Leave out the quote card above the chart.")
@pass_app
def chart(
    app: App,
    symbol: str,
    period: str | None,
    versus: tuple[str, ...],
    height: int,
    as_json: bool,
    as_csv: bool,
    stats: bool,
    start: str | None,
    end: str | None,
    last: int | None,
    normalize: bool,
    width: int | None,
    no_card: bool,
) -> None:
    """Braille price chart, optionally compared against other symbols.

    --json, --csv and --stats print the fetched series instead of drawing it;
    --from, --to and --last trim that series without fetching anything else.
    """
    if as_json and as_csv:
        raise click.UsageError("Choose one output format: --json or --csv.")
    drawing = {"--normalize": normalize, "--width": width is not None, "--no-card": no_card}
    if as_json or as_csv or stats:
        if used := [name for name, on in drawing.items() if on]:
            raise click.UsageError(f"{', '.join(used)} only change the drawn chart, not --json, --csv or --stats.")
    if start and end and start > end:
        raise click.UsageError("--from must be on or before --to.")
    period = period or app.config.chart_period
    market = app.tracker.market
    machine = as_json or as_csv
    sym = symbol.upper()
    try:
        with nullcontext() if machine else app.busy(f"Fetching {sym} {period}…"):
            bars = market.history(symbol, period)
            others = {v.upper(): market.history(v, period) for v in versus}
            quotes, _ = market.quotes([symbol])
    except MarketError as e:
        fail(str(e))
    if start or end or last:
        fetched = bool(bars)
        bars = _trim(bars, start, end, last)
        others = {k: _trim(v, start, end, last) for k, v in others.items()}
        if fetched and not bars:
            fail(f"No {sym} {period} bars in the selected range.")
    q = quotes.get(sym)
    if stats:
        rows = [_series_stats(sym, bars, period), *(_series_stats(k, v, period) for k, v in others.items())]
        if as_json:
            click.echo(json.dumps(rows, ensure_ascii=False))
        elif as_csv:
            click.echo(_csv_text(STATS_FIELDS, rows), nl=False)
        else:
            app.console.print(_stats_table(rows, period))
        return
    if as_json:
        payload = {
            "symbol": sym,
            "period": period,
            "interval": PERIOD_INTERVALS[period],
            "currency": q.currency if q else None,
            "bars": [_bar_json(sym, b) for b in bars],
            "vs": {k: [_bar_json(k, b) for b in v] for k, v in others.items()},
        }
        click.echo(json.dumps(payload, ensure_ascii=False))
        return
    if as_csv:
        series = [(sym, bars), *others.items()]
        click.echo(_csv_text(CHART_FIELDS, [_bar_json(k, b) for k, v in series for b in v]), nl=False)
        return
    if q and not no_card:
        app.console.print(render.quote_card(q))
        app.console.print()
    chart_width = width if width is not None else app.console.width - 1
    if normalize and not others and bars:
        app.console.print(_normalized_chart(sym, bars, period, app.palette, width=chart_width, height=height))
        return
    app.console.print(
        render.price_chart(
            sym,
            bars,
            period,
            app.palette,
            width=chart_width,
            height=height,
            quote=q,
            compare=others or None,
        )
    )


def _compare_row(symbol: str, bars: list[Bar], period: str) -> dict:
    from ..analytics import max_drawdown, period_return, volatility

    closes = [b.close for b in bars]
    interval = PERIOD_INTERVALS[period]
    return {
        "symbol": symbol,
        "period": period,
        "interval": interval,
        "from": bars[0].date,
        "to": bars[-1].date,
        "bars": len(bars),
        "start": closes[0],
        "end": closes[-1],
        "return_pct": period_return(closes),
        "max_drawdown_pct": max_drawdown(closes),
        "volatility_pct": volatility(closes, BARS_PER_YEAR[interval]),
        "vs_base_pp": None,
    }


def _order_compare(rows: list[dict], sort: str | None, reverse: bool, *, measured_first: bool = False) -> list[dict]:
    if sort == "drawdown":
        rows = sorted(rows, key=lambda r: r["max_drawdown_pct"], reverse=True)  # shallowest first
    elif sort == "volatility":
        rows = sorted(rows, key=lambda r: r["volatility_pct"] or 0.0)  # calmest first
    elif sort == "symbol":
        rows = sorted(rows, key=lambda r: r["symbol"])
    else:  # return, best first: the order `compare` has always used
        rows = sorted(rows, key=lambda r: r["return_pct"] or 0, reverse=True)
    if reverse:
        rows.reverse()
    if sort == "volatility":
        # Too few bars to measure stays last either way (the sort is stable).
        rows.sort(key=lambda r: r["volatility_pct"] is None)
    elif measured_first and sort in (None, "return"):
        # Plain `compare` ranks an unmeasured return as 0; when ordering is asked for, it goes last.
        rows.sort(key=lambda r: r["return_pct"] is None)
    return rows


@main.command()
@click.argument("symbols", nargs=-1, required=True)
@click.option("-p", "--period", type=click.Choice(PERIODS), default="1y", show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Print the comparison rows as JSON, no chart.")
@click.option("--csv", "as_csv", is_flag=True, help="Print the comparison rows as CSV, no chart.")
@click.option(
    "--sort",
    type=click.Choice(COMPARE_SORTS),
    help="Order rows by return (best first, the default), drawdown (shallowest first), volatility (calmest first) "
    "or symbol.",
)
@click.option("--reverse", is_flag=True, help="Reverse the row order.")
@click.option("--base", help="Add each return minus this compared symbol's return, in percentage points.")
@click.option("--top", type=click.IntRange(min=1), help="Keep only the first N rows after ordering (chart too).")
@click.option("--no-chart", is_flag=True, help="Print only the comparison table.")
@pass_app
def compare(
    app: App,
    symbols: tuple[str, ...],
    period: str,
    as_json: bool,
    as_csv: bool,
    sort: str | None,
    reverse: bool,
    base: str | None,
    top: int | None,
    no_chart: bool,
) -> None:
    """Compare returns, drawdown and volatility across symbols.

    --sort, --reverse, --top and --base reorder and annotate the same histories;
    --json and --csv print the rows for scripts.
    """
    if as_json and as_csv:
        raise click.UsageError("Choose one output format: --json or --csv.")
    if no_chart and (as_json or as_csv):
        raise click.UsageError("--json and --csv never draw a chart; drop --no-chart.")
    syms = parse_symbols(" ".join(symbols))
    base_sym = None
    if base is not None:
        picked = parse_symbols(base)
        if len(picked) != 1:
            raise click.UsageError("--base takes one symbol.")
        base_sym = picked[0]
        if base_sym not in syms:
            raise click.UsageError(f"--base {base_sym} must be one of the compared symbols.")
    market = app.tracker.market
    machine = as_json or as_csv
    data = {}
    with nullcontext() if machine else app.busy(f"Fetching {len(syms)} histories…"):
        for s in syms:
            try:
                data[s] = market.history(s, period)
            except MarketError as e:
                if machine:
                    click.echo(f"! {e}", err=True)
                else:
                    app.warn(str(e))
    data = {k: v for k, v in data.items() if v}
    if not data:
        fail("No data retrieved.")
    rows = _order_compare(
        [_compare_row(s, bars, period) for s, bars in data.items()],
        sort,
        reverse,
        measured_first=sort is not None or reverse or top is not None,
    )
    if base_sym is not None:
        base_row = next((r for r in rows if r["symbol"] == base_sym), None)
        if base_row is None:
            fail(f"{base_sym}: no {period} history to compare against.")
        for r in rows:
            if r["return_pct"] is not None and base_row["return_pct"] is not None:
                r["vs_base_pp"] = r["return_pct"] - base_row["return_pct"]
    if top:
        rows = rows[:top]
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
        return
    if as_csv:
        click.echo(_csv_text(COMPARE_FIELDS, rows), nl=False)
        return
    shown = {r["symbol"] for r in rows}
    if not no_chart:
        first, *rest = [s for s in data if s in shown]
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
    headers: list = [
        "Symbol",
        ("Start", "right"),
        ("End", "right"),
        ("Return", "right"),
        ("Max drawdown", "right"),
        ("Volatility", "right"),
    ]
    if base_sym is not None:
        headers.append((f"vs {base_sym}", "right"))
    t = render.table(*headers, title=f"\n{period} comparison")
    for r in rows:
        ret = r["return_pct"]
        cells = [
            Text(r["symbol"], style="bright"),
            Text(fmt.price(r["start"]), style="muted"),
            Text(fmt.price(r["end"])),
            render.trend(fmt.pct(ret), ret),
            Text(fmt.pct(r["max_drawdown_pct"]), style="down"),
            Text(fmt.pct(r["volatility_pct"], sign=False), style="muted"),
        ]
        if base_sym is not None:
            gap = r["vs_base_pp"]
            if r["symbol"] == base_sym:
                cells.append(Text("base", style="muted"))
            else:
                cells.append(render.trend(f"{gap:+,.2f} pp" if gap is not None else render.DASH, gap))
        t.add_row(*cells)
    app.console.print(t)


def _type_key(text: str) -> str:
    """`Mutual Fund`, `MUTUALFUND` and `mutual-fund` all compare equal."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


@main.command()
@click.argument("query", nargs=-1, required=True)
@click.option("--json", "as_json", is_flag=True, help="Print the matches as JSON.")
@click.option("--csv", "as_csv", is_flag=True, help="Print the matches as CSV.")
@click.option("--type", "types", multiple=True, help="Keep this result type: ETF, Equity, Mutual fund… (repeatable).")
@click.option("--exchange", "exchanges", multiple=True, help="Keep exchanges containing this text (repeatable).")
@click.option("--limit", type=click.IntRange(1, SEARCH_LIMIT), help=f"Show at most N matches (1–{SEARCH_LIMIT}).")
@click.option("--first", is_flag=True, help="Print only the top matching symbol, for scripts.")
@pass_app
def search(
    app: App,
    query: tuple[str, ...],
    as_json: bool,
    as_csv: bool,
    types: tuple[str, ...],
    exchanges: tuple[str, ...],
    limit: int | None,
    first: bool,
) -> None:
    """Find symbols by company or fund name.

    --type, --exchange and --limit narrow the same results; --json, --csv and
    --first print them for scripts.
    """
    if as_json and as_csv:
        raise click.UsageError("Choose one output format: --json or --csv.")
    if first and (as_json or as_csv):
        raise click.UsageError("--first prints a bare symbol; it can't be combined with --json or --csv.")
    if any(not t.strip() for t in types):
        raise click.UsageError("--type cannot be blank.")
    if any(not x.strip() for x in exchanges):
        raise click.UsageError("--exchange cannot be blank.")
    wanted_types = {_type_key(t) for t in types}
    wanted_exchanges = [x.strip().lower() for x in exchanges]
    quiet = as_json or as_csv or first
    try:
        with nullcontext() if quiet else app.busy("Searching…"):
            results = app.tracker.market.search(" ".join(query), limit=SEARCH_LIMIT)
    except MarketError as e:
        fail(str(e))
    filtered = bool(wanted_types or wanted_exchanges)
    if filtered:
        results = [
            r
            for r in results
            if (not wanted_types or _type_key(r.type) in wanted_types)
            and (not wanted_exchanges or any(x in r.exchange.lower() for x in wanted_exchanges))
        ]
    if limit:
        results = results[:limit]
    if as_json or as_csv:
        rows = [{"symbol": r.symbol, "name": r.name, "exchange": r.exchange, "type": r.type} for r in results]
        if as_json:
            click.echo(json.dumps(rows, ensure_ascii=False))
        else:
            click.echo(_csv_text(SEARCH_FIELDS, rows), nl=False)
        if not results:
            click.get_current_context().exit(1)
        return
    if not results:
        fail("No matches for --type/--exchange." if filtered else "No matches.")
    if first:
        click.echo(results[0].symbol)
        return
    app.console.print(render.search_table(results))
