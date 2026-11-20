"""Market data: quotes, charts, comparisons and symbol search."""

from __future__ import annotations

import csv
import io
import json
import math
import re
import time
from contextlib import nullcontext
from datetime import date, datetime
from itertools import pairwise

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
MOVE_DIRECTIONS = ("up", "down")
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


def _finite_price(ctx: click.Context, param: click.Parameter, value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("must be a finite price", ctx=ctx, param=param)
    return value


def _finite_percent(ctx: click.Context, param: click.Parameter, value: float | None) -> float | None:
    if value is not None and not math.isfinite(value):
        raise click.BadParameter("must be a finite percentage", ctx=ctx, param=param)
    return value


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
@click.option("--jsonl", "as_jsonl", is_flag=True, help="Print one JSON quote object per line (live or --cached).")
@click.option(
    "--min-move",
    type=click.FloatRange(min=0),
    callback=_finite_percent,
    help="Live: keep only symbols whose day change is at least this many percent either way.",
)
@click.option("--direction", type=click.Choice(MOVE_DIRECTIONS), help="Live: keep only rising or falling quotes.")
@click.option("--summary", is_flag=True, help="Live: add a breadth line (up, down, unchanged, average % change).")
@click.option(
    "--check-above",
    type=float,
    callback=_finite_price,
    help="Exit 1 unless every named symbol has a fresh quote at or above this price.",
)
@click.option(
    "--check-below",
    type=float,
    callback=_finite_price,
    help="Exit 1 unless every named symbol has a fresh quote at or below this price.",
)
@click.option("--fail-on-stale", is_flag=True, help="Exit 1 when any live quote came from the offline cache.")
@click.option("--count", "count_only", is_flag=True, help="With --cached: print how many cached quotes match.")
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
    as_jsonl: bool,
    min_move: float | None,
    direction: str | None,
    summary: bool,
    check_above: float | None,
    check_below: float | None,
    fail_on_stale: bool,
    count_only: bool,
) -> None:
    """Live quotes. One symbol shows a detail card.

    With --cached, read only the saved offline cache; --all, --currency, --search,
    --older-than, --newer-than, --sort, --descending, --csv and --count refine that view.
    --field prints bare live values; --strict exits 1 when any symbol is missing.
    --min-move and --direction narrow live quotes; --check-above, --check-below and
    --fail-on-stale exit 1 for scripts, and stale quotes never pass a price check.
    """
    if field and (cached or as_json):
        raise click.UsageError("--field prints live values; it can't be combined with --cached or --json.")
    if as_jsonl and (as_json or as_csv or field):
        raise click.UsageError("Choose one output format: --jsonl, --json, --csv or --field.")
    if strict and cached:
        raise click.UsageError("--strict applies to live quotes, not --cached.")
    live_only = {
        "--min-move": min_move is not None,
        "--direction": direction is not None,
        "--summary": summary,
        "--check-above": check_above is not None,
        "--check-below": check_below is not None,
        "--fail-on-stale": fail_on_stale,
    }
    if cached and (live := [name for name, on in live_only.items() if on]):
        verb = "applies" if len(live) == 1 else "apply"
        raise click.UsageError(f"{', '.join(live)} {verb} to live quotes, not --cached.")
    if summary and (as_json or as_jsonl or field):
        raise click.UsageError("--summary adds a line to the table; it can't be used with --json, --jsonl or --field.")
    if count_only and (as_json or as_csv or as_jsonl):
        raise click.UsageError("--count prints a number; it can't be combined with --json, --jsonl or --csv.")
    if check_above is not None and check_below is not None and check_above > check_below:
        raise click.UsageError("--check-above must be at or below --check-below.")
    cache_opts = {
        "--all": all_cached,
        "--currency": bool(currencies),
        "--search": search is not None,
        "--older-than": older_than is not None,
        "--newer-than": newer_than is not None,
        "--sort": sort is not None,
        "--descending": descending,
        "--csv": as_csv,
        "--count": count_only,
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
            as_jsonl=as_jsonl,
            count_only=count_only,
        )
        return
    if as_json or field or as_jsonl:
        quotes, errors = app.tracker.market.quotes(syms)
    else:
        with app.busy("Fetching quotes…"):
            quotes, errors = app.tracker.market.quotes(syms)
    found = any(s in quotes for s in syms)
    missing = any(s not in quotes for s in syms)
    narrowed = min_move is not None or direction is not None
    # Named symbols without a quote stay listed, so their errors are still shown.
    shown = [s for s in syms if s not in quotes or _moves(quotes[s], min_move, direction)] if narrowed else syms
    problems = _check_problems(syms, quotes, errors, check_above, check_below, fail_on_stale)
    machine = bool(as_json or as_jsonl or field)
    if field:
        _print_field(shown, quotes, errors, field, labelled=len(syms) > 1)
    elif as_json or as_jsonl:
        rows = [_quote_json(s, quotes.get(s), errors) for s in shown]
        click.echo(json.dumps(rows, ensure_ascii=False) if as_json else _jsonl(rows), nl=as_json or bool(rows))
    elif len(syms) == 1 and not narrowed:
        q = quotes.get(syms[0])
        if q is None:
            fail(f"{syms[0]}: {errors.get(syms[0], 'no data')}")
        app.console.print(render.quote_card(q))
    elif not shown:
        app.console.print(Text("No quotes match --min-move/--direction.", style="muted"))
    else:
        app.console.print(render.quotes_table(shown, quotes, errors, width=app.console.width))
    if summary:
        app.console.print(_breadth([quotes[s] for s in shown if s in quotes]))
    for message in problems:
        if machine:
            click.echo(f"! {message}", err=True)
        else:
            app.warn(message)
    if (machine and not found) or (strict and missing) or problems:
        click.get_current_context().exit(1)


def _jsonl(rows: list[dict]) -> str:
    """JSON Lines: one compact object per line, no trailing newline (click.echo adds it)."""
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)


def _moves(q: Quote, min_move: float | None, direction: str | None) -> bool:
    """Whether a live quote's day change passes --min-move and --direction."""
    if min_move is not None and abs(q.change_pct) < min_move:
        return False
    if direction == "up":
        return q.change > 0
    if direction == "down":
        return q.change < 0
    return True


def _check_problems(
    syms: list[str],
    quotes: dict[str, Quote],
    errors: dict[str, str],
    above: float | None,
    below: float | None,
    fail_on_stale: bool,
) -> list[str]:
    """Why a --check-above/--check-below/--fail-on-stale run fails; a stale quote never passes a price check."""
    checking = above is not None or below is not None
    problems = []
    for s in syms:
        q = quotes.get(s)
        if q is None:
            if checking:
                problems.append(f"{s}: no quote to check ({errors.get(s, 'no data')}).")
            continue
        if q.stale and (checking or fail_on_stale):
            problems.append(f"{s}: quote is stale (from the offline cache).")
            continue
        if above is not None and q.price < above:
            problems.append(f"{s} {fmt.price(q.price)} is below {fmt.price(above)}.")
        if below is not None and q.price > below:
            problems.append(f"{s} {fmt.price(q.price)} is above {fmt.price(below)}.")
    return problems


def _breadth(quotes: list[Quote]) -> Text:
    """`Breadth: 2 up · 1 down · 0 unchanged · average +1.23%` over the shown quotes."""
    if not quotes:
        return Text("Breadth: no quotes.", style="muted")
    up = sum(q.change > 0 for q in quotes)
    down = sum(q.change < 0 for q in quotes)
    avg = sum(q.change_pct for q in quotes) / len(quotes)
    line = Text(f"Breadth: {up} up · {down} down · {len(quotes) - up - down} unchanged · average ", style="muted")
    line.append(fmt.pct(avg), style=fmt.trend_style(avg))
    return line


def _print_field(
    syms: list[str], quotes: dict[str, Quote], errors: dict[str, str], field: str, *, labelled: bool
) -> None:
    """One value per line: bare for one symbol, `SYMBOL<tab>value` for several; misses go to stderr."""
    for s in syms:
        q = quotes.get(s)
        if q is None:
            click.echo(f"{s}: {errors.get(s, 'no data')}", err=True)
            continue
        value = getattr(q, field)
        text = "" if value is None else str(value)
        click.echo(f"{s}\t{text}" if labelled else text)


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
    as_jsonl: bool = False,
    count_only: bool = False,
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
    if count_only:
        click.echo(len(shown))
        return
    if as_json or as_csv or as_jsonl:
        rows = [_quote_json(s, shown.get(s), errors) for s in order]
        if as_json:
            click.echo(json.dumps(rows, ensure_ascii=False))
        elif as_jsonl:
            click.echo(_jsonl(rows), nl=bool(rows))
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
RESAMPLES = ("week", "month")
# Yahoo suffixes for Canadian listings: TSX, TSX Venture, CSE and Cboe Canada (NEO).
CANADIAN_SUFFIXES = (".TO", ".V", ".CN", ".NE")
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


def _resample(bars: list[Bar], every: str) -> list[Bar]:
    """Keep the last bar of each ISO week or calendar month (exchange dates), in order."""
    last: dict[object, Bar] = {}
    for b in bars:
        key: object = date.fromisoformat(b.date).isocalendar()[:2] if every == "week" else b.date[:7]
        last[key] = b
    return list(last.values())


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
@click.option("--jsonl", "as_jsonl", is_flag=True, help="Print the bars (or --stats rows) as JSON Lines, no chart.")
@click.option(
    "--resample",
    type=click.Choice(RESAMPLES),
    help="With --json, --csv or --jsonl: keep each week's or month's last bar (after --from/--to/--last).",
)
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
    as_jsonl: bool,
    resample: str | None,
) -> None:
    """Braille price chart, optionally compared against other symbols.

    --json, --csv, --jsonl and --stats print the fetched series instead of drawing it;
    --from, --to and --last trim that series without fetching anything else, and
    --resample thins printed bars to one per week or month.
    """
    if as_json and as_csv:
        raise click.UsageError("Choose one output format: --json or --csv.")
    if as_jsonl and (as_json or as_csv):
        raise click.UsageError("Choose one output format: --json, --csv or --jsonl.")
    drawing = {"--normalize": normalize, "--width": width is not None, "--no-card": no_card}
    if as_json or as_csv or as_jsonl or stats:
        if used := [name for name, on in drawing.items() if on]:
            outputs = "--json, --csv, --jsonl or --stats" if as_jsonl else "--json, --csv or --stats"
            raise click.UsageError(f"{', '.join(used)} only change the drawn chart, not {outputs}.")
    if resample and (stats or not (as_json or as_csv or as_jsonl)):
        raise click.UsageError("--resample applies to --json, --csv or --jsonl bars, not --stats or the drawn chart.")
    if start and end and start > end:
        raise click.UsageError("--from must be on or before --to.")
    period = period or app.config.chart_period
    market = app.tracker.market
    machine = as_json or as_csv or as_jsonl
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
    if resample:
        bars = _resample(bars, resample)
        others = {k: _resample(v, resample) for k, v in others.items()}
    q = quotes.get(sym)
    if stats:
        rows = [_series_stats(sym, bars, period), *(_series_stats(k, v, period) for k, v in others.items())]
        if as_json:
            click.echo(json.dumps(rows, ensure_ascii=False))
        elif as_jsonl:
            click.echo(_jsonl(rows))
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
    if as_csv or as_jsonl:
        series = [(sym, bars), *others.items()]
        rows = [_bar_json(k, b) for k, v in series for b in v]
        if as_jsonl:
            click.echo(_jsonl(rows), nl=bool(rows))
        else:
            click.echo(_csv_text(CHART_FIELDS, rows), nl=False)
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
@click.option("--since", callback=date_callback, help="Measure from this date: drop fetched bars before it.")
@click.option(
    "--min-return",
    type=float,
    callback=_finite_price,
    help="Keep only symbols whose return is at least this many percent.",
)
@click.option("--strict", is_flag=True, help="Exit 1 when any symbol has no history to compare.")
@click.option(
    "--correlation",
    is_flag=True,
    help="Print the correlation of bar-to-bar returns between each pair (common dates only), no chart.",
)
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
    since: str | None,
    min_return: float | None,
    strict: bool,
    correlation: bool,
) -> None:
    """Compare returns, drawdown and volatility across symbols.

    --sort, --reverse, --top, --min-return and --base reorder and annotate the same
    histories; --since measures from a date; --correlation prints a return-correlation
    matrix instead; --json and --csv print the rows for scripts.
    """
    if as_json and as_csv:
        raise click.UsageError("Choose one output format: --json or --csv.")
    if no_chart and (as_json or as_csv):
        raise click.UsageError("--json and --csv never draw a chart; drop --no-chart.")
    if correlation:
        table_only = {
            "--sort": sort is not None,
            "--reverse": reverse,
            "--base": base is not None,
            "--top": top is not None,
            "--min-return": min_return is not None,
            "--no-chart": no_chart,
        }
        if used := [name for name, on in table_only.items() if on]:
            raise click.UsageError(f"{', '.join(used)} can't be combined with --correlation.")
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
    if since:
        data = {k: _trim(v, since, None, None) for k, v in data.items()}
    data = {k: v for k, v in data.items() if v}
    if not data:
        fail("No data retrieved." if not since else f"No data on or after {since}.")
    absent = [s for s in syms if s not in data]
    if correlation:
        _print_correlation(app, data, period, as_json=as_json, as_csv=as_csv)
        _strict_exit(app, absent, period, strict=strict, machine=machine)
        return
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
    if min_return is not None:
        rows = [r for r in rows if r["return_pct"] is not None and r["return_pct"] >= min_return]
        if not rows:
            fail(f"No symbol returned at least {min_return:g}% over {period}.")
    if top:
        rows = rows[:top]
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
        _strict_exit(app, absent, period, strict=strict, machine=True)
        return
    if as_csv:
        click.echo(_csv_text(COMPARE_FIELDS, rows), nl=False)
        _strict_exit(app, absent, period, strict=strict, machine=True)
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
    _strict_exit(app, absent, period, strict=strict, machine=False)


def _strict_exit(app: App, absent: list[str], period: str, *, strict: bool, machine: bool) -> None:
    """With --strict, name each symbol that had no history and exit 1."""
    if not (strict and absent):
        return
    for s in absent:
        message = f"{s}: no {period} history to compare."
        if machine:
            click.echo(f"! {message}", err=True)
        else:
            app.warn(message)
    raise click.exceptions.Exit(1)


def _return_series(bars: list[Bar], intraday: bool) -> dict:
    """Close by bar key: the exchange date for daily and longer bars, the timestamp for intraday ones."""
    return {(b.time if intraday else b.date): b.close for b in bars}


def _correlation(a: dict, b: dict) -> float | None:
    """Pearson correlation of bar-to-bar returns over the keys both series share; None if too few."""
    keys = sorted(set(a) & set(b))
    ra, rb = [], []
    for k1, k2 in pairwise(keys):
        if a[k1] and b[k1]:
            ra.append(a[k2] / a[k1] - 1)
            rb.append(b[k2] / b[k1] - 1)
    if len(ra) < 3:
        return None
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    if va <= 0 or vb <= 0:
        return None
    return max(-1.0, min(1.0, cov / math.sqrt(va * vb)))


def _print_correlation(app: App, data: dict[str, list[Bar]], period: str, *, as_json: bool, as_csv: bool) -> None:
    if len(data) < 2:
        fail("--correlation needs at least two symbols with history.")
    intraday = PERIOD_INTERVALS[period][-1] in "mh"
    series = {s: _return_series(bars, intraday) for s, bars in data.items()}
    syms = list(series)
    rows: list[dict] = [
        {"symbol": s, **{o: 1.0 if s == o else _correlation(series[s], series[o]) for o in syms}} for s in syms
    ]
    if as_json:
        click.echo(json.dumps(rows, ensure_ascii=False))
        return
    if as_csv:
        click.echo(_csv_text(["symbol", *syms], rows), nl=False)
        return
    t = render.table("Symbol", *((s, "right") for s in syms), title=f"{period} return correlation")
    for r in rows:
        cells = [Text(r["symbol"], style="bright")]
        for o in syms:
            v = r[o]
            cells.append(Text(render.DASH if v is None else f"{v:+.2f}", style="muted" if o == r["symbol"] else ""))
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
@click.option("--canadian", is_flag=True, help="Keep only Canadian listings (.TO, .V, .CN and .NE symbols).")
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
    canadian: bool,
) -> None:
    """Find symbols by company or fund name.

    --type, --exchange, --canadian and --limit narrow the same results; --json, --csv and
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
    if canadian:
        results = [r for r in results if r.symbol.upper().endswith(CANADIAN_SUFFIXES)]
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
        if canadian and not filtered:
            fail("No Canadian listings match.")
        fail("No matches for --type/--exchange." if filtered else "No matches.")
    if first:
        click.echo(results[0].symbol)
        return
    app.console.print(render.search_table(results))
